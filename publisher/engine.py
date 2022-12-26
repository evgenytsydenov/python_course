import glob
import hashlib
import os
import shutil
from typing import Any, Iterable

from google.oauth2 import service_account
from googleapiclient.discovery import Resource, build
from googleapiclient.http import MediaFileUpload

from settings import PUBLISH_IGNORE
from utils.app_logger import get_logger

logger = get_logger(__name__)


class GDrivePublisher:
    """Use Google Drive API to publish files.

    Attributes:
        cloud_root_name: Name of the cloud folder where files will be placed.
    """

    def __init__(self, creds: dict[str, Any], cloud_root_name: str) -> None:
        """Create GDrive publisher.

        Args:
            creds: Google Drive credentials.
            cloud_root_name: Name of the root folder where the files will be placed.
        """
        self.cloud_root_name = cloud_root_name
        self._creds = creds
        self._scopes = ["https://www.googleapis.com/auth/drive"]
        self._ignored_files = PUBLISH_IGNORE
        self._gd_resource: Resource | None = None
        self._gd_root_folder_id: str | None = None

    @property
    def _gdrive(self) -> Resource:
        if self._gd_resource is None:
            raise RuntimeError('The method "connect" must be called first.')
        return self._gd_resource

    @property
    def _cloud_root_folder_id(self) -> str:
        if self._gd_root_folder_id is None:
            raise RuntimeError('The method "connect" must be called first.')
        return self._gd_root_folder_id

    def connect(self) -> None:
        """Find the root cloud folder and build the GDrive resource."""
        self._gd_resource = self._build_resource()
        query = (
            f"mimeType = 'application/vnd.google-apps.folder' "
            f"and name = '{self.cloud_root_name}' "
            f"and trashed != True"
        )
        cloud_folder_id = self._find_cloud_objs(query, attributes=["id"])
        if cloud_folder_id:
            self._gd_root_folder_id = cloud_folder_id[0]["id"]
            logger.debug(
                f'The root cloud folder "{self.cloud_root_name}" with '
                f'the id "{self._gd_root_folder_id}" was found.'
            )
        else:
            raise ValueError(
                f'The root cloud folder for publishing "{self.cloud_root_name}" must be'
                f" pre created and shared with the user whose credentials are provided."
            )
        logger.info("GDrive publisher started successfully.")

    def _create_cloud_path(self, cloud_path: str) -> str:
        """Create all intermediate folders on the way to the cloud path.

        Args:
            cloud_path: Path of the cloud folder that is relative
                to the root cloud folder.

        Returns:
            ID of the leaf folder.
        """
        parent_id = self._cloud_root_folder_id
        if cloud_path == ".":
            return parent_id
        for name in cloud_path.split(os.sep):
            query = f"name = '{name}' and '{parent_id}' in parents and trashed != True"
            folder = self._find_cloud_objs(query, ["id"])
            parent_id = (
                folder[0]["id"]
                if folder
                else self._create_cloud_folder(name, parent_id)
            )
        return parent_id

    def sync(
        self,
        local_obj: str,
        cloud_folder_path: str = ".",
        link_type: str = "webViewLink",
        to_share: bool = True,
    ) -> str:
        """Sync the local file or folder with the cloud one.

        Args:
            local_obj: Path to the local file or folder to sync.
            cloud_folder_path: Path to the folder where to upload content of the local
                object. It should be passed as a relative path from the root cloud
                folder and should not contain the object itself.
            link_type: Type of the link to return (webViewLink, webContentLink, etc.)
            to_share: Whether to share the file to anyone with link for read-only
                access.

        Returns:
            Link to the file or folder in the cloud.
        """
        if not os.path.exists(local_obj):
            raise ValueError(f'The local path "{local_obj}" does not exist.')

        # Sanitize
        if os.path.isdir(local_obj):
            self._sanitize_local_folder(local_obj)

        # Get id of the parent folder
        local_name = os.path.basename(local_obj)
        cloud_name = os.path.join(cloud_folder_path, local_name)
        parent_id = self._create_cloud_path(cloud_folder_path)

        # Find the file or folder and sync it
        query = (
            f"name = '{local_name}' and '{parent_id}' in parents "
            f"and trashed != True"
        )
        cloud_obj = self._find_cloud_objs(query, ["id"])
        if cloud_obj:
            cloud_obj_id = cloud_obj[0]["id"]
            logger.debug(
                f'File or folder "{local_name}" exists '
                f'in the cloud path "{cloud_folder_path}".'
            )
            self._update_cloud_obj(cloud_obj_id, local_obj)
        else:
            logger.debug(
                f'File or folder "{local_name}" does not exist '
                f'in the cloud path "{cloud_folder_path}".'
            )
            cloud_obj_id = self._upload_local_obj(local_obj, parent_id)
        logger.debug(
            f'Content of the local object "{local_obj}" was synchronized with '
            f'the cloud file "{cloud_name}" with the id "{cloud_obj_id}".'
        )

        # Share
        if link_type == "const_thumbnail":
            obj_params = self._get_cloud_obj_attributes(
                cloud_obj_id, ["permissions", "name"]
            )
            obj_params[
                link_type
            ] = f"https://drive.google.com/thumbnail?id={cloud_obj_id}"
        else:
            obj_params = self._get_cloud_obj_attributes(
                cloud_obj_id, ["permissions", link_type, "name"]
            )
        if to_share:
            is_shared = any(
                (p["id"] == "anyoneWithLink") and (p["role"] == "reader")
                for p in obj_params["permissions"]
            )
            if is_shared:
                logger.debug(
                    f'File or folder "{obj_params["name"]}" with the '
                    f'id "{cloud_obj_id}" is already shared.'
                )
            else:
                self._share_cloud_obj(cloud_obj_id)
                logger.debug(
                    f'File or folder "{obj_params["name"]}" with the '
                    f'id "{cloud_obj_id}" was shared with a link '
                    f"to anyone for reading."
                )
        return str(obj_params[link_type])

    def _update_cloud_obj(self, cloud_obj_id: str, path_local_obj: str) -> None:
        """Update content of the cloud file or folder.

        Args:
            cloud_obj_id: ID of the file of folder in the cloud.
            path_local_obj: Path to the local file or folder.
        """
        # If it is a file
        if not os.path.isdir(path_local_obj):
            c_file = self._get_cloud_obj_attributes(cloud_obj_id, ["id", "md5Checksum"])
            if c_file["md5Checksum"] != self._get_md5_hash(path_local_obj):
                media = MediaFileUpload(path_local_obj, resumable=True)
                self._gdrive.files().update(
                    fileId=cloud_obj_id, media_body=media
                ).execute()
                logger.debug(
                    f'Cloud file with the id "{cloud_obj_id}" was updated '
                    f'with content from the local path "{path_local_obj}"'
                )

        # If it is a directory
        else:
            query = f"'{cloud_obj_id}' in parents and trashed != True"
            cloud_content = {
                f["name"]: f for f in self._find_cloud_objs(query, ["id", "name"])
            }
            cloud_names = set(cloud_content.keys())
            local_content = self._get_local_content(path_local_obj)
            local_names = set(local_content.keys())
            for common in cloud_names.intersection(local_names):
                self._update_cloud_obj(
                    cloud_content[common]["id"], local_content[common]["path"]
                )
            for cloud_drop in cloud_names.difference(local_names):
                self._remove_cloud_file(cloud_content[cloud_drop]["id"])
            for cloud_add in local_names.difference(cloud_names):
                self._upload_local_obj(local_content[cloud_add]["path"], cloud_obj_id)

    def _share_cloud_obj(self, obj_id: str) -> None:
        """Share the file or folder to anyone with a link.

        Args:
            obj_id: ID of the file or folder in the cloud to share.
        """
        permissions = {"type": "anyone", "role": "reader"}
        self._gdrive.permissions().create(fileId=obj_id, body=permissions).execute()
        logger.debug(
            f'Permissions of the file of folder with the id "{obj_id}" '
            f'was modified to "{permissions}".'
        )

    def _upload_local_obj(self, path_local_obj: str, parent_id: str) -> str:
        """Upload the local file or folder to Google Drive.

        Args:
            path_local_obj: Path to the local file or folder.
            parent_id: ID of the cloud folder where to upload.

        Returns:
            ID of the uploaded file or folder.
        """
        # If it is a folder
        if os.path.isdir(path_local_obj):
            dir_name = os.path.basename(path_local_obj)
            folder_id = self._create_cloud_folder(dir_name, parent_id)
            for obj_name in os.listdir(path_local_obj):
                path = os.path.join(path_local_obj, obj_name)
                self._upload_local_obj(path, folder_id)
            logger.debug(
                f'Folder "{path_local_obj}" was uploaded '
                f'to the cloud folder with the id "{parent_id}".'
            )
            return folder_id

        # If it is a file
        obj_name = os.path.split(path_local_obj)[-1]
        file_metadata = {"name": obj_name, "parents": [parent_id]}
        media = MediaFileUpload(path_local_obj, resumable=True)
        file = (
            self._gdrive.files()
            .create(body=file_metadata, fields="id", media_body=media)
            .execute()
        )
        logger.debug(
            f'File "{path_local_obj}" was uploaded to the cloud '
            f'folder with the id "{parent_id}".'
        )
        return str(file["id"])

    def _get_local_content(self, path_folder: str) -> dict[str, Any]:
        """Get content of the local folder.

        Args:
            path_folder: Path to the local folder.

        Returns:
            Names and hashes of files and folders.
        """
        result = {}
        for file in os.listdir(path_folder):
            path = os.path.join(path_folder, file)
            result[file] = {"path": path}
            if not os.path.isdir(path):
                result[file]["md5hash"] = self._get_md5_hash(path)
        return result

    # TODO: This should not remove files
    def _sanitize_local_folder(self, path: str) -> None:
        """Clean the local folder from unnecessary files.

        Args:
            path: Path of the folder to clean.
        """
        for pattern in self._ignored_files:
            path_ = os.path.join(path, pattern)
            to_drop = glob.glob(path_, recursive=True)
            for file in to_drop:
                shutil.rmtree(file)
                logger.debug(f'File "{file}" was sanitized.')

    def _build_resource(self) -> Resource:
        """Build the Google Drive API resource.

        Returns:
            Resource for interactions.
        """
        credentials = service_account.Credentials.from_service_account_info(
            self._creds, scopes=self._scopes
        )
        resource = build("drive", "v3", credentials=credentials)
        logger.debug("New GDrive resource was created.")
        return resource

    def _get_md5_hash(self, path_file: str) -> str:
        """Get md5 hash of the file.

        Args:
            path_file: Path to the local file.

        Returns:
            Hash value.
        """
        hasher = hashlib.md5()
        with open(path_file, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hasher.update(chunk)
        return hasher.hexdigest()

    def _create_cloud_folder(self, name: str, parent_obj_id: str) -> str:
        """Create empty the cloud folder.

        Args:
            name: Name of the folder to create.
            parent_obj_id: ID of the parent folder.

        Returns:
            ID of the created folder.
        """
        meta = {
            "name": name,
            "mimeType": "application/vnd.google-apps.folder",
            "parents": [parent_obj_id],
        }
        folder = self._gdrive.files().create(body=meta, fields="id").execute()
        logger.debug(
            f'The cloud folder "{name}" was created with the id "{folder["id"]}".'
        )
        return str(folder["id"])

    def _remove_cloud_file(self, obj_id: str) -> None:
        """Remove the file or folder from the cloud.

        Args:
            obj_id: ID of the file or folder.
        """
        self._gdrive.files().delete(fileId=obj_id).execute()
        logger.debug(f'File or folder with the id "{obj_id}" was removed.')

    def _find_cloud_objs(
        self, query: str, attributes: Iterable[str]
    ) -> list[dict[str, Any]]:
        """Find files and folders in accordance to the query.

        Args:
            query: Filter query.
            attributes: Attributes of files or folders to load.

        Returns:
            List of files and folders with the attributes.
        """
        fields = f'nextPageToken, files({", ".join(attributes)})'
        results: dict[str, Any] = (
            self._gdrive.files().list(q=query, fields=fields).execute()
        )
        logger.debug(
            "Attributes of the files corresponding to the query were downloaded."
        )

        next_page_token = results.get("nextPageToken")
        while next_page_token:
            next_page = (
                self._gdrive.files()
                .list(q=query, fields=fields, pageToken=next_page_token)
                .execute()
            )
            logger.debug("Loaded the next page of the query results.")
            next_page_token = next_page.get("nextPageToken")
            results["files"] += next_page["files"]
        files: list[dict[str, Any]] = results["files"]
        return files

    def _get_cloud_obj_attributes(
        self, file_id: str, attributes: Iterable[str]
    ) -> dict[str, Any]:
        """Get attributes of the cloud file or folder.

        Args:
            file_id: ID of the file or folder.
            attributes: Attributes to get.

        Returns:
            Attributes.
        """
        fields = f'{", ".join(attributes)}'
        attrs: dict[str, Any] = (
            self._gdrive.files().get(fileId=file_id, fields=fields).execute()
        )
        logger.debug(f'Attributes of the file "{file_id}" were loaded.')
        return attrs
