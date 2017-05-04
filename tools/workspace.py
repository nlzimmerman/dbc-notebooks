#!/usr/bin/env python

import base64
import argparse
import json
import requests
import sys
import os
import fnmatch

from operator import itemgetter

WS_LIST = "/workspace/list"
WS_STATUS = "/workspace/get-status"
WS_MKDIRS = "/workspace/mkdirs"
WS_IMPORT = "/workspace/import"
WS_EXPORT = "/workspace/export"
LS_ZONES = "/clusters/list-zones"
#
WS_LIST = "/workspace/list"

error_401 = """
Credentials are incorrect. Please verify the credentials passed into the APIs.
If using SSO, log out of the Databricks environment.
1. Click on the Admin login page
2. Enter your e-mail
3. Click 'Forgot my Password'
This will create a new password for you to use against the REST API. This should **not** be your SSO password
"""


class WorkspaceClient(object):
    """A class to define wrappers for the REST API"""

    # NLZ -- I would probably remove the defaults here, since they aren't useful
    # (there's no "default" situation in which they do anything)
    def __init__(self, host="https://myenv.cloud.databricks.com", user="admin", pwd="fakePassword", is_shared=False, debug = False):
        self.user = user
        self.pwd = pwd
        self.creds = (user, pwd)
        self.host = host
        self.is_shared = is_shared
        self.url = host.rstrip('/') + '/api/2.0'
        self.debug = debug

    def get(self, endpoint, json_params={}, print_json=False):
        url = self.url + endpoint
        if json_params:
            raw_results = requests.get(url, auth=self.creds, params=json_params)
        else:
            raw_results = requests.get(url, auth=self.creds)
        if raw_results.status_code == 401:
            print(error_401)
            raise ValueError("Unauthorized error")
        results = raw_results.json()
        if print_json:
            print(json.dumps(results, indent=4, sort_keys=True))
        return results

    def post(self, endpoint, json_params={}, print_json=True):
        url = self.url + endpoint
        if json_params:
            raw_results = requests.post(url, auth=self.creds, json=json_params)
            results = raw_results.json()
        else:
            print("Must have a payload in json_args param.")
            return {}
        if print_json:
            print(json.dumps(results, indent=4, sort_keys=True))
        # if results are empty, let's return the return status
        if results:
            results['http_status_code'] = raw_results.status_code
            return results
        else:
            return {'http_status_code': raw_results.status_code}

    # NLZ — I don't honestly know how this is different than
    # def my_map(F, items):
    #   return list(map(F, items))
    @staticmethod
    def my_map(F, items):
        to_return = []
        for elem in items:
            to_return.append(F(elem))
        return to_return


    def is_file(self, path):
        """ Checks if the file is a notebook or folder in Databricks"""
        if path=='/':
            return False
        status = {'path': path}
        resp = self.get(WS_STATUS, json_params=status)
        if resp.get('error_code', None):
            print(resp)
            raise NameError('File does not exist in Databricks workspace.')
        # I added a debug property to this class to make this quieter.
        if self.debug:
            print("Is the path a file or folder: ")
            print(resp)
        if resp['object_type'] == 'DIRECTORY':
            return False
        return True

    def get_full_path(self, in_path):
        """ Get the full path of the Databricks workspace
         User's can provide the relative path to push / pull from Databricks"""
        path = in_path.lstrip('[\"\']').rstrip('[\"\']')
        if path[0] == '/':
            # return path is absolute so return here
            return path
        elif path[0] == '.':
            full_path = '/Users/' + self.user.strip() + path[1:]
            return full_path
        elif str.isalnum(path[0]):
            full_path = '/Users/' + self.user.strip() + '/' + path
            return full_path
        else:
            raise ValueError('Path should start with . for relative paths or / for absolute.')

    def save_single_notebook(self, fullpath):
        """ Saves a single notebook from Databricks to the local directory"""
        get_args = {'path': fullpath}
        resp = self.get(WS_EXPORT, get_args)
        if resp.get('error_code', None):
            if to_skip:
                print('\n\nSkipping file due to error :' + fullpath + '\n\n')
                return
            else:
                print(resp)
                raise NameError('File does not exist in Databricks workspace.')
        # grab the relative path from the constructed full path
        # this code chops of the /Users/mwc@example.com/ to create a local reference
        save_filename = '/'.join(fullpath.split('/')[3:]) + '.' + resp['file_type']
        if self.is_shared:
            save_filename = self.user.split("@")[0] + '/' + save_filename
        save_path = os.path.dirname(save_filename)
        print("Local path to save: " + save_path)
        print("Saving file in local path: " + save_filename)
        # If the local path doesn't exist,we create it before we save the contents
        if not os.path.exists(save_path) and save_path:
            os.makedirs(save_path)
        with open(save_filename, "wb") as f:
            f.write(base64.b64decode(resp['content']))

    def get_all_notebooks(self, fullpath):
        """ Recursively list all notebooks within the folder"""
        get_args = {'path': fullpath}
        items = self.get(WS_LIST, get_args)['objects']
        folders = list(self.my_map(lambda y: y.get('path', None),
                      filter(lambda x: x.get('object_type', None) == 'DIRECTORY', items)))
        notebooks = list(self.my_map(lambda y: y.get('path', None),
                        filter(lambda x: x.get('object_type', None) == 'NOTEBOOK', items)))
        print('DIRECTORIES: ' + str(folders))
        print('NOTEBOOKS: ' + str(notebooks))
        if folders == [] and notebooks == []:
            print('Folder does not contain any notebooks')
            return []
        # save the notebooks with the current method
        if notebooks:
            self.my_map(lambda y: self.save_single_notebook(y), notebooks)
        if folders:
            nested_list_notebooks = list(self.my_map(lambda y: self.get_all_notebooks(y), folders))
            flatten_list = [item for sublist in nested_list_notebooks for item in sublist]
            return notebooks + flatten_list
        return notebooks

    def save_folder(self, fullpath):
        """ We will save the notebooks within the paths, and exclude Library links """
        list_of_notebooks = self.get_all_notebooks(fullpath)
        return list_of_notebooks
        # Run map of save_single_notebook across list of notebooks

    def pull(self, path):
        # get_args = "/Users/mwc@databricks.com/demo/reddit/Reddit SQL Analysis"
        cur_path = self.get_full_path(path)

        # pull the file or archive
        if self.is_file(cur_path):
            self.save_single_notebook(cur_path)
        else:
            self.save_folder(cur_path)

    @staticmethod
    def _parse_extension(src_path):
        supported = ['scala', 'py', 'r', 'sql']
        ext = src_path.split('.')[-1]
        if ext == 'scala':
            return {'language': 'SCALA'}
        elif ext == 'py':
            return {'language': 'PYTHON'}
        elif ext == 'ipynb':
            return {'format': 'JUPYTER'}
        elif ext == 'r':
            return {'language': 'R'}
        elif ext == 'sql':
            return {'language': 'SQL'}
        elif ext == 'txt':
            return {'language': 'SQL'}
        else:
            raise ValueError('Unsupported file format: %s. Supported formats are: ' % ext +
                             '[%s].' % ', '.join(supported))

    def push_file(self, local_path, dst_folder = None):
        """Push a single file to DBC
          This assumes the local path matches the Databricks workspace"""
        # get the databricks path using the users hostname
        if self.is_shared:
            username = self.user.split('@')[0]
            tmp_path = '/Users/' + self.user.strip() + '/' + local_path.lstrip('./').replace(username + '/', "")
        elif dst_folder:
            tmp_path = '/Users/' + self.user.strip() + '/' + dst_folder.replace('/', '') + '/' + local_path.lstrip('./')
        else:
            tmp_path = '/Users/' + self.user.strip() + '/' + local_path.lstrip('./')
        overwrite = True
        dirname = os.path.dirname(tmp_path)
        dbc_path, file_ext = os.path.splitext(tmp_path)
        data = open(local_path, 'r').read()
        create_notebook = {
           "path": dbc_path,
           "content": base64.b64encode(data.encode('utf-8')).decode(),
           "overwrite": overwrite
        }
        create_notebook.update(self._parse_extension(local_path))
        # create a folder, if exists then it succeeds as well
        folder_resp = self.post(WS_MKDIRS, {'path': dirname}, False)
        # import the notebook
        resp = self.post(WS_IMPORT, create_notebook, False)
        print("Push Notebook: " + dbc_path)
        print(resp)

    @staticmethod
    def find_all_file_paths(local_dir):
        matches = []
        supported = ['scala', 'py', 'r', 'sql']
        for root, dirnames, filenames in os.walk(local_dir):
            for ext in supported:
                for filename in fnmatch.filter(filenames, '*.' + ext):
                    matches.append(os.path.join(root, filename))
        return matches

    def push_folder(self, local_path):
        """ Find all source files first, grab all the folders, batch create folders, push notebooks"""
        file_list = self.find_all_file_paths(local_path)
        cwd = os.getcwd()
        file_list_rel_path = list(self.my_map(lambda x: x.replace(cwd, "."), file_list))
        for fname in file_list_rel_path:
            self.push_file(fname)
        return file_list_rel_path

    def push(self, path):
        if path[0] == '/':
            raise ValueError("Path should be relative to your git repo home dir and start with ./ or with folder name")
        if os.path.isfile(path):
            self.push_file(path)
        else:
            self.push_folder(path)

    def ls(self, path):
        def printer(file_info):
            if file_info['object_type'] == "NOTEBOOK":
                return file_info['language'].ljust(10)+file_info['path']
            elif file_info['object_type'] == "DIRECTORY":
                return file_info['object_type'].ljust(10)+file_info['path']
            else:
                raise Exception("Don't understand object type {}".format(file_info['object_type']))
        full_path = self.get_full_path(path)
        if self.is_file(full_path):
            #
            file_info = self.get(WS_STATUS, json_params={"path": full_path})
            return printer(file_info)
        else:
            #return json.dumps(self.get(WS_LIST, json_params={"path": self.get_full_path(path)}), indent=4)
            dir_info = self.get(WS_LIST, json_params={"path": full_path})['objects']
            # we are exploiting the fact that 'DIRECTORY' comes before 'NOTEBOOK' in a lexical sort
            # to list the directories first
            return '\n'.join(printer(x) for x in sorted(dir_info, key=itemgetter('object_type', 'path')))

if __name__ == '__main__':
    to_skip = False
    debug = False
    parser = argparse.ArgumentParser(description="""
    Sync Databricks workspace to/from local directory for git support.
    e.g.
    $ python workspaces.py pull demo/reddit/
    $ python workspaces.py push demo/reddit/
    Or
    $ python workspaces.py pull --host='https://myenv.cloud.databricks.com/ --user=mwc@databricks.com --password=HAHAHA
    I personally use the environment variables to store this information
    DBC_HOST
    DBC_USERNAME
    DBC_PASSWORD
    DBC_SHARED
    DBC_SHARED is set to true if the single repo needs to host multiple home directories.
    It creates a local directory from the users e-mail
    """)
    # subparser for mutually exclusive arguments
    sp = parser.add_subparsers(dest='action')
    sp_push = sp.add_parser('push', help='Push path to Databricks workspace')
    sp_pull = sp.add_parser('pull', help='Pull workspace from Databricks to local directory')
    sp_ls = sp.add_parser('ls', help='List workspace')

    parser.add_argument('--user', dest='user', help='Username for the Databricks env')
    parser.add_argument('--password', dest='password', help='Password for the Databricks env')
    parser.add_argument('--host', dest='host', help='Password for the Databricks env')

    parser.add_argument('--shared', dest='shared', action='store_true',
                        help='Boolean to notify if this is a \
                        shared repo to add a username prefix to the directories')
    parser.add_argument('--skip', dest='to_skip', action='store_true',
                        help='Boolean to skip any errors or not')

    parser.add_argument('path', type=str,
                        help='The path/directory in Databricks or locally to sync')

    args = parser.parse_args()
    # the arguments
    user = args.user
    host = args.host
    password = args.password
    is_shared = args.shared
    if args.to_skip:
        to_skip = True
    if not host:
        host = os.environ.get('DBC_HOST')
    if not user:
        user = os.environ.get('DBC_USERNAME')
    if not password:
        password = os.environ.get('DBC_PASSWORD')
    if not is_shared:
        is_shared = bool(os.environ.get('DBC_SHARED'))
    helper = WorkspaceClient(host, user, password, is_shared)

    if debug:
        print("ACTION IS: " + args.action)
        print("PATH IS: " + args.path)
        print("USER IS: " + user)
        print("PASS IS: " + "I_DONT_PRINT_PASSWORDS")
        print("HOST IS: " + host)
    if args.path is None:
        print("Need path")
        exit(0)
    else:
        input_path = args.path
        if args.action.lower() == "push":
            helper.push(input_path)
        elif args.action.lower() == "pull":
            helper.pull(input_path)
        elif args.action.lower() == "ls":
            print(helper.ls(input_path))
        else:
            print("Push / pull are only supported as the action.")
