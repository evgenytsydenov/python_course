import glob
import hashlib
import os
import shutil
from typing import Any
from typing import Dict
from typing import Iterable
from typing import List

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

from utils.app_logger import get_logger

logger = get_logger(__name__)


class GDrivePublisher:
    """Use Google Drive API to publish files."""

    def __init__(self, creds: Dict[str, Any], cloud_root_name: str) -> None:
        """Create GDrive publisher.

        :param creds: Google Drive credentials.
        :param cloud_root_name: name of root folder where to publish.
        """
        self.cloud_root_name = cloud_root_name
        self._creds = creds
        self._scopes = ['https://www.googleapis.com/auth/drive']
        self._ignore_files = self._get_ignore_files()
        self._gdrive = None
        self._cloud_root_id = None

    def connect(self) -> None:
        """Find root cloud folder and build GDrive resource."""

        # Build resource
        self._gdrive = self._build_resource()

        # Get id of cloud folder
        query = f"mimeType = 'application/vnd.google-apps.folder' " \
                f"and name = '{self.cloud_root_name}' " \
                f"and trashed != True"
        cloud_file_id = self._find_cloud_files(query, attributes=['id'])
        if not cloud_file_id:
            raise ValueError('The root cloud folder for publishing must be '
                             'pre created.')
        self._cloud_root_id = cloud_file_id[0]['id']

    def _create_cloud_path(self, cloud_path: str) -> str:
        """Create all intermediate folders on the way to the cloud path.

        :param cloud_path: path of cloud folder that is relative to the
        root cloud folder.
        :return: id of the leaf folder.
        """
        parent_id = self._cloud_root_id
        if cloud_path == '.':
            return parent_id
        for name in cloud_path.split(os.sep):
            query = f"name = '{name}' and '{parent_id}' in parents " \
                    f"and trashed != True"
            folder = self._find_cloud_files(query, ['id'])
            if not folder:
                parent_id = self._create_cloud_folder(name, parent_id)
            else:
                parent_id = folder[0]['id']
        return parent_id

    def sync(self, local_file: str, cloud_folder_path: str = '.',
             link_type: str = 'webViewLink', to_share: bool = True) -> str:
        """Sync a local file or folder with the cloud one.

        :param to_share: to share file to anyone with link for read-only
        access.
        :param cloud_folder_path: path to a folder where to upload content
        of the local file. It should be passed as a relative path from the
        root cloud folder and should not contain the file itself.
        :param link_type: type of link to return (webViewLink,
        webContentLink, etc.)
        :param local_file: path to local file or folder with the object itself.
        :return link to the file.
        """
        if not os.path.exists(local_file):
            raise ValueError(f'The local path "{local_file}" does not exist.')

        # Sanitize
        if os.path.isdir(local_file):
            self._sanitize_local_folder(local_file)

        # Get id of the parent folder
        local_name = os.path.basename(local_file)
        cloud_name = os.path.join(cloud_folder_path, local_name)
        parent_id = self._create_cloud_path(cloud_folder_path)

        # Find the file and sync it
        query = f"name = '{local_name}' and '{parent_id}' in parents " \
                f"and trashed != True"
        cloud_file = self._find_cloud_files(query, ['id'])
        if not cloud_file:
            logger.debug(f'File or folder "{local_name}" does not exist '
                         f'in the cloud path "{cloud_folder_path}".')
            cloud_file_id = self._upload_file(local_file, parent_id)
        else:
            cloud_file_id = cloud_file[0]['id']
            logger.debug(f'File or folder "{local_name}" exists '
                         f'in the cloud path "{cloud_folder_path}".')
            self._update_cloud_file(cloud_file_id, local_file)
        logger.debug(f'Content of the local object "{local_file}" was '
                     f'synchronized with the cloud file "{cloud_name}".')

        # Share
        if link_type == 'const_thumbnail':
            file_params = self._get_cloud_file(
                cloud_file_id, ['permissions', 'name'])
            file_params[link_type] = f'http://drive.google.com/' \
                                     f'thumbnail?id={cloud_file_id}'
        else:
            file_params = self._get_cloud_file(
                cloud_file_id, ['permissions', link_type, 'name'])
        if to_share:
            is_shared = False
            for p in file_params['permissions']:
                if (p['id'] == 'anyoneWithLink') and (p['role'] == 'reader'):
                    is_shared = True
            if is_shared:
                logger.debug(f'File or folder "{file_params["name"]}" with '
                             f'id "{cloud_file_id}" is already shared.')
            else:
                self._share_cloud_file(cloud_file_id)
                logger.debug(f'File or folder "{file_params["name"]}" with '
                             f'id "{cloud_file_id}" was shared with link '
                             f'to anyone for reading.')
        return file_params[link_type]

    def _update_cloud_file(self, file_id: str, path_local_file: str) -> None:
        """Change cloud file content.

        :param file_id: id of file.
        :param path_local_file: path to local file or folder.
        """
        # If file
        if not os.path.isdir(path_local_file):
            c_file = self._get_cloud_file(file_id, ['id', 'md5Checksum'])
            if c_file['md5Checksum'] != self._get_md5_hash(path_local_file):
                media = MediaFileUpload(path_local_file, resumable=True)
                self._gdrive.files().update(fileId=file_id,
                                            media_body=media).execute()
                logger.debug(f'File "{file_id}" was updated '
                             f'with content from "{path_local_file}"')

        # If directory
        else:
            query = f"'{file_id}' in parents and trashed != True"
            cloud_content = self._find_cloud_files(query, ['id', 'name'])
            cloud_content = {f['name']: f for f in cloud_content}
            cloud_names = set(cloud_content.keys())
            local_content = self._get_local_content(path_local_file)
            local_names = set(local_content.keys())
            for common in cloud_names.intersection(local_names):
                self._update_cloud_file(cloud_content[common]['id'],
                                        local_content[common]['path'])
            for cloud_drop in cloud_names.difference(local_names):
                self._remove_cloud_file(cloud_content[cloud_drop]['id'])
            for cloud_add in local_names.difference(cloud_names):
                self._upload_file(local_content[cloud_add]['path'], file_id)

    def _share_cloud_file(self, file_id: str) -> None:
        """Share file to anyone with a link.

        :param file_id: id of file to share.
        """
        permissions = {'type': 'anyone', 'role': 'reader'}
        self._gdrive.permissions() \
            .create(fileId=file_id, body=permissions).execute()
        logger.debug(f'Permissions of file with id "{file_id}" '
                     f'was modified to "{permissions}".')

    def _upload_file(self, path_local_file: str, parent_id: str) -> str:
        """Upload local file or folder to Google Drive.

        :param path_local_file: path to local file or folder.
        :param parent_id: id of the cloud folder where to upload.
        :return file id.
        """
        # If it is a folder
        if os.path.isdir(path_local_file):
            dir_name = os.path.basename(path_local_file)
            folder_id = self._create_cloud_folder(dir_name, parent_id)
            for obj_name in os.listdir(path_local_file):
                path = os.path.join(path_local_file, obj_name)
                self._upload_file(path, folder_id)
            logger.debug(f'Folder "{path_local_file}" was uploaded '
                         f'to the cloud folder with id "{parent_id}".')
            return folder_id

        # If it is a file
        obj_name = os.path.split(path_local_file)[-1]
        file_metadata = {'name': obj_name, 'parents': [parent_id]}
        media = MediaFileUpload(path_local_file, resumable=True)
        file = self._gdrive.files().create(
            body=file_metadata, fields='id', media_body=media).execute()
        logger.debug(f'File "{path_local_file}" was uploaded to the cloud '
                     f'folder with id "{parent_id}".')
        return file['id']

    def _get_local_content(self, path_folder) -> Dict[str, Any]:
        """Get content of local folder.

        :param path_folder: path to local folder.
        :return: names and hash of files and folders.
        """
        result = {}
        for file in os.listdir(path_folder):
            path = os.path.join(path_folder, file)
            result[file] = {'path': path}
            if not os.path.isdir(path):
                result[file]['md5hash'] = self._get_md5_hash(path)
        return result

    def _sanitize_local_folder(self, path: str) -> None:
        """Clean local folder from unnecessary files.

        :param path: path of folder to clean.
        """
        for pattern in self._ignore_files:
            path_ = os.path.join(path, pattern)
            to_drop = glob.glob(path_, recursive=True)
            for file in to_drop:
                shutil.rmtree(file)
                logger.debug(f'File "{file}" was sanitized.')

    def _build_resource(self) -> Any:
        """Build Google Drive api resource.

        :return: resource for interaction.
        """
        credentials = service_account.Credentials.from_service_account_info(
            self._creds, scopes=self._scopes)
        resource = build('drive', 'v3', credentials=credentials)
        logger.debug('New GDrive resource was created.')
        return resource

    def _get_md5_hash(self, path_file: str) -> str:
        """Get md5 hash of a file.

        :param path_file: path to local file.
        :return: hash value.
        """
        hasher = hashlib.md5()
        with open(path_file, 'rb') as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hasher.update(chunk)
        return hasher.hexdigest()

    def _create_cloud_folder(self, name: str, parent_id: str) -> str:
        """Create empty cloud folder.

        :param name: name of folder.
        :param parent_id: id of parent folder.
        :return: id of new folder.
        """
        meta = {
            'name': name,
            'mimeType': 'application/vnd.google-apps.folder',
            'parents': [parent_id]
        }
        file = self._gdrive.files().create(body=meta, fields='id').execute()
        logger.debug(f'Cloud folder "{name}" was created '
                     f'with id "{file["id"]}".')
        return file['id']

    def _remove_cloud_file(self, file_id: str) -> None:
        """Remove file or folder from the cloud.

        :param file_id: id of file.
        """
        self._gdrive.files().delete(fileId=file_id).execute()
        logger.debug(f'File or folder with id "{file_id}" was removed.')

    def _find_cloud_files(self, query: str, attributes: Iterable[str]) \
            -> List[Dict[str, Any]]:
        """Get files attributes in accordance to the query.

        :param attributes: attributes to load.
        :param query: filter query.
        :return: list with attributes of each file in specified folder.
        """
        fields = f'nextPageToken, files({", ".join(attributes)})'
        results = self._gdrive.files().list(q=query, fields=fields).execute()
        next_page_token = results.get('nextPageToken')
        while next_page_token:
            next_page = self._gdrive.files().list(
                q=query, fields=fields, pageToken=next_page_token).execute()
            next_page_token = next_page.get('nextPageToken')
            results['files'] += next_page['files']
        return results['files']

    def _get_cloud_file(self, file_id: str, attributes: Iterable[str]) \
            -> Dict[str, Any]:
        """Get attributes of cloud file.

        :param file_id: if of file.
        :param attributes: attributes to get.
        :return: dict with attributes.
        """
        fields = f'{", ".join(attributes)}'
        results = self._gdrive.files().get(
            fileId=file_id, fields=fields).execute()
        return results

    def _get_ignore_files(self) -> List[str]:
        """Get file patterns to ignore when publishing.

        :return: file patterns.
        """
        patterns = []
        path = os.path.join(os.path.dirname(__file__), '.publishignore')
        with open(path, 'r') as file:
            for line in file.readlines():
                if line.strip() and not line.startswith('#'):
                    patterns.append(line)
        logger.debug('Publish ignore files were loaded.')
        return patterns
