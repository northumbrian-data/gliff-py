import base64
import json
import time
from decouple import config, UndefinedValueError
from loguru import logger
from etebase import Client, Account, Collection, Item, CollectionManager, ItemManager
from PIL import Image
from io import BytesIO
from typing import Literal, Union, Optional, Any, List, Dict


ToolboxType = Literal["paintbrush", "spline", "boundingBox"]


class Project:
    def __init__(self, account: Account, project_uid: str) -> None:
        self.reset_values(account, project_uid)

    def reset_values(self, account: Account, project_uid: str) -> None:
        """Reset all project values."""
        self.account = account
        self.project_uid = project_uid
        self.project_mng = self._fetch_project_manager(account)
        self.project = self._fetch_project(self.project_mng, project_uid)
        self.item_mng = self._fetch_item_manager(self.project_mng, self.project)

    def _fetch_project_manager(self, account: Account) -> CollectionManager:
        """Fetch the project manager.

        Parameters
        ----------
        account: Account
            Instance of the main Etebase class.
        Return
        ------
        project_mng: CollectionManager
            Etebase's collection manager.
        """
        logger.info("fetching project manager...")
        project_mng = account.get_collection_manager()
        logger.success("project manager fetched.")

        return project_mng

    def _fetch_project(self, project_mng: CollectionManager, project_uid: str) -> Collection:
        """Fetch project data.

        Parameters
        ----------
        project_mng: CollectionManager
            Etebase's collection manager.
        project_uid: str
            Project's uid.
        Return
        ------
        project: Collection
            Project data.
        """
        logger.info("fetching project...")
        project = project_mng.fetch(project_uid)
        logger.success("project fetched.")
        return project

    def _fetch_item_manager(self, project_mng: CollectionManager, project: Collection) -> ItemManager:
        """Fetch item manager.

        Parameters
        ----------
        project_mng: ItemManager
            Etebase's item manager.
        project: Collection
            Project data.
        Return
        ------
        item_mng: ItemManager
            Etebase's item manager.
        """
        logger.info("fetching item manager...")
        item_mng = project_mng.get_item_manager(project)
        logger.success("item manager fetched.")
        return item_mng

    def update_project_data(self, account: Account, project_uid: str) -> None:
        """If the account or the project uid have changed, reset all values."""
        if account != self.account or project_uid != self.project_uid:
            logger.info("updating project data...")
            self.reset_values(account, project_uid)
            logger.success("updated project data.")

    def get_content(self) -> Any:
        """Get the project's content."""
        return self.project.content

    def set_content(self, content: Any) -> None:
        """Set the project's content."""
        self.project.content = content
        self.project_mng.transaction(self.project)


class Gliff:
    def __init__(self) -> None:
        self.project: Union[Project, None] = None

    def get_value(self, env_variable: str) -> Any:
        """
        Use this if you want to enforce (in order of priority):
        1. a passed parameter (env_variable)
        2. an environment variable being set
        3. an env var being set in .env
        """
        # check for actually passed value first
        try:
            passed_value = globals()[env_variable]
            if passed_value is not None:
                return passed_value
            else:
                # otherwise check for env variable
                env_value = config(env_variable)
                return env_value
        except KeyError:
            raise UndefinedValueError(f"{env_variable} not found.")

    def base64_to_pil_image(self, img_base64: Union[str, bytes]) -> Image.Image:
        """Convert a base64-encoded image into a PIL Image object"""

        img_bytes = base64.b64decode(img_base64)
        img_file = BytesIO(img_bytes)
        return Image.open(img_file).convert("RGB")

    def pil_to_base64_image(self, img_pil: Image.Image, is_thumbnail: Optional[bool] = False) -> str:
        """Convert a PIL Image object to a base64-encoded image (in bytes)"""

        img_file = BytesIO()
        img_pil.save(img_file, format="PNG")
        img_bytes = img_file.getvalue()
        img_base64 = base64.b64encode(img_bytes).decode()
        if is_thumbnail:
            img_base64 = f"data:image/png;base64,{img_base64}"
        return img_base64

    def _get_thumbnail_from_pil_image(self, img_pil: Image.Image) -> str:
        """Get base64-encoded thumbnail (in bytes) from PIL image"""

        size = 128, 128
        img_pil.thumbnail(size, Image.ANTIALIAS)
        return self.pil_to_base64_image(img_pil, True)

    def decode_content(self, content: bytes) -> Any:
        """Extract and decode project's or item's content, from binary to Dict."""
        try:
            return json.loads(content.decode())
        except json.JSONDecodeError as e:
            logger.warning(f"Error while accessing the project's content: {e}.")

    def encode_content(self, decoded_content: Any) -> bytes:
        """Encode project's or item's content, from Dict to binary."""
        return json.dumps(decoded_content, separators=(",", ":")).encode()

    def get_current_time(self) -> int:
        """Get the current UTC time as an integer number expressed in milliseconds since the epoch."""
        return int(round(time.time() * 1000))

    def is_empty_annotation(self, annotation: Dict[str, Any]) -> bool:
        """Check if an annotation is empty."""
        return (
            (len(annotation["spline"]["coordinates"]) == 0)
            & (len(annotation["brushStrokes"]) == 0)
            & (annotation["boundingBox"]["coordinates"]["topLeft"]["x"] is None)
        )

    def create_brush_stroke(
        self,
        coordinates: List[Union[int, float]],
        spaceTimeInfo: Optional[Dict[str, Any]] = {
            "z": 0,
            "t": 0,
        },
        brush: Optional[Dict[str, Any]] = {
            "radius": 0.5,
            "type": "paint",
            "color": "rgba(170, 0, 0, 0.5)",
            "is3D": False,
        },
    ) -> Optional[Dict[str, Any]]:
        """Create a brush stroke annotation."""

        return {
            "coordinates": coordinates,
            "spaceTimeInfo": spaceTimeInfo,
            "brush": brush,
        }

    def create_annotation(
        self,
        toolbox: ToolboxType,
        labels: List[str] = [],
        spline: Optional[Dict[str, Any]] = {
            "coordinates": [],
            "spaceTimeInfo": {"z": 0, "t": 0},
            "isClosed": False,
        },
        bounding_box: Optional[Dict[str, Any]] = {
            "coordinates": {
                "topLeft": {"x": None, "y": None},
                "bottomRight": {"x": None, "y": None},
            },
            "spaceTimeInfo": {"z": 0, "t": 0},
        },
        brush_strokes: Optional[List[Optional[Dict[str, Any]]]] = [],
        parameters: Optional[Dict[str, Any]] = {},
    ) -> Dict[str, Any]:
        """Create an annotation.

        Parameters:
        -----------
        tooltip: Toolbox
            Annotate toolbox.
        labels: List[str]
            Image-wise labels.
        spline: Optional[Dict]
            Spline data.
        bounding_box: Optional[Dict]
            Bounding-box data.
        brush_strokes: Optional[Dict]
            Brush-strokes data.
        parameters: Optional[Dict]
            Annotation's parameters.
        Return:
        -------
        annotation:
            Annotation (empty by default)

        """

        return {
            "toolbox": toolbox,
            "labels": labels,
            "spline": spline,
            "boundingBox": bounding_box,
            "brushStrokes": brush_strokes,
            "parameters": parameters,
        }

    def _process_image_data(self, image: Union[str, Image.Image]) -> Union[None, Dict[str, Any]]:
        """Create, encrypt and upload a new item to the STORE project.

        Parameters
        ----------
        image: PIL.Image.Image or str
            Image uploaded to the new item.
        Returns
        -------
        image_data: Dict or None
            A dictionary that includes image width, height, thumbnail and the ecoded image.
        """

        # check type of image and process it
        if type(image) == Image.Image:
            image_pil = image
            image = self.pil_to_base64_image(image)
        elif isinstance(image, str):
            image_pil = self.base64_to_pil_image(image)
        else:
            logger.error("image should be of type PIL.Image.Image or str")
            return None

        width, height = image_pil.size
        return {
            "width": width,
            "height": height,
            "thumbnail": self._get_thumbnail_from_pil_image(image_pil),
            "encoded_image": self.encode_content([[image]]),
        }

    def login(self, access_key: str, server_url: str) -> Any:
        """Log in to STORE.

        Parameters
        ----------
        username: str
            Plugin's access key.
        server_url: str
            Server URL.
        Returns
        -------
        account: Account
            Instance of the main Etebase class.
        """

        logger.info("logging in to STORE...")

        client = Client("client-name", server_url)
        username, password = base64.b64decode(access_key).decode("ascii").split(":")
        account = Account.login(client, username, password)
        logger.success("logged in.")

        self._accept_pending_invitations(account)

        return account

    def logout(self, account: Account) -> None:
        """Log out of STORE.

        Parameters
        ----------
        account: Account
            Instance of the main Etebase class.
        """

        logger.info("logging out...")
        account.logout()
        logger.success("logged out.")

    def _accept_pending_invitations(self, account: Account) -> None:
        """Accept all pending invitations to join a STORE project.

        Parameters
        ----------
        account: Account
            Instance of the main Etebase class.
        """

        invit_mng = account.get_invitation_manager()

        invitations = invit_mng.list_incoming()
        logger.info(f"pending invitations: {invitations}")

        for invitation in list(invitations.data):

            invit_mng.accept(invitation)
            logger.success("invitations accepted.")

    def _leave_project(self, account: Account, project_uid: str) -> None:
        """Leave a project.

        Parameters
        ----------
        account: Account
            Instance of the main Etebase class.
        project_uid: str
            Project's uid.
        """
        self.update_project_data(account, project_uid)

        logger.info(f"leaving project, uid: {project_uid}...")
        memeber_mng = self.project.project_mng.get_member_manager(self.project.project)
        memeber_mng.leave()
        logger.info("left project.")

    def update_project_data(self, account: Account, project_uid: str) -> None:
        """Update project data if either account or project_uid have changed.

        Parameters:
        -----------
        account: Account
            Instance of the main Etebase class.
        project_uid: str
            Project's uid.
        """

        if self.project is None:
            self.project = Project(account, project_uid)
        else:
            self.project.update_project_data(account, project_uid)

    def get_project_item(self, account: Account, project_uid: str, item_uid: str) -> Item:
        """Retrieve a project's item.

        Parameters
        ----------
        account: Account
            Instance of the main Etebase class.
        project_uid: str
            Project's uid.
        item_uid: str
            Item uid.
        Returns
        -------
        item: Item
            Project's item
        """

        self.update_project_data(account, project_uid)

        try:
            logger.info(f"fetching item, uid: {item_uid}...")
            item = self.project.item_mng.fetch(item_uid)
            logger.info("item fetched.")
            return item
        except Exception as e:
            logger.error(f"error while fetching image: {e}.")

    def _create_tile_update(
        self,
        image_labels: Optional[List[str]] = None,
        metadata: Dict[str, Any] = {},
        annotation_uid: Dict[str, str] = {},
        audit_uid: Dict[str, str] = {},
        annotation_complete: Dict[str, bool] = {},
    ) -> Dict[str, Any]:
        """Create gallery tile with data to update.

        Parameters:
        -----------
        image_labels: List[str]
            Image-wise labels.
        metadata: Dict
            Metadata.
        annotation_uid: Dict[str, str]
            Annotation items linked to the image item.
        audit_uid: Dict[str, str]
            Audit items linked to the image item.
        annotation_complete: Dict[str, bool]
            Whether annotations are complete or not.

        Returns:
        --------
        tile: Dist
            Gallery tile.
        """

        tile = {
            "metadata": metadata,
            "annotationUID": annotation_uid,
            "auditUID": audit_uid,
            "annotationComplete": annotation_complete,
        }

        if image_labels is not None:
            tile["imageLabels"] = image_labels

        return tile

    def _create_new_tile(
        self,
        image_item_uid: str,
        thumbnail: str,
        image_labels: List[str] = [],
        metadata: Dict[str, Any] = {},
        annotation_uid: Dict[str, str] = {},
        audit_uid: Dict[str, str] = {},
        annotation_complete: Dict[str, bool] = {},
    ) -> Dict[str, Any]:
        """Create new gallery tile.

        Parameters:
        -----------
        image_item_uid: str
            Image item's uid (also tile's id).
        thumbnail: resized, base64-encoded image
            Thumbnail for the image uploaded.
        image_labels: List[str]
            Image-wise labels.
        metadata: Dict
            Metadata.
        annotation_uid: Dict[str, str]
            Annotation items linked to the image item.
        audit_uid: Dict[str, str]
            Audit items linked to the image item.
        annotation_complete: Dict[str, bool]
            Whether annotations are complete or not.

        Returns:
        --------
        tile: Dist
            Gallery tile.
        """

        return {
            "id": image_item_uid,
            "thumbnail": thumbnail,
            "imageLabels": image_labels,
            "metadata": metadata,
            "imageUID": image_item_uid,
            "annotationUID": annotation_uid,
            "auditUID": audit_uid,
            "annotationComplete": annotation_complete,
        }

    def _create_gallery_tile(self, tile: Dict[str, Any]) -> None:
        """Create, ecrypt and upload a new tile to the STORE project.

        Parameters
        ----------
        tile: Dict
            New gallery tile.
        """

        logger.info("updating gallery's content..")

        try:
            gallery = self._get_gallery()

            gallery.append(tile)

            self._set_gallery(gallery)
        except Exception as e:
            logger.error(f"Error while creating a gallery's tile: {e}")

    def _get_gallery(self) -> List[Dict[str, Any]]:
        return self.decode_content(self.project.get_content())

    def _find_gallery_tile(self, gallery: List[Dict[str, Any]], id: str) -> Union[int, None]:
        """Get the index for the gallery tile corresponding to the image item with
        uid equal to the galler's id (or equal to the imageUID field)."""
        for i, tile in enumerate(gallery):
            if tile["id"] == id:
                return i
        return None

    def _set_gallery(self, gallery: List[Dict[str, Any]]) -> None:
        self.project.set_content(self.encode_content(gallery))

    def _update_gallery_tile(self, item_uid: str, tile_data: Dict[str, Any]) -> None:
        """Update a tile in the STORE project.
        Parameters
        ----------
        item_uid: str
            Item uid (the item is of type gliff.image).
        tile_data: Dict
            Gallery tile data.
        """

        def update_tile(
            tile: Dict[str, Any],
            metadata: Optional[Dict[str, Any]] = None,
            annotationUID: Optional[Dict[str, str]] = None,
            auditUID: Optional[Dict[str, str]] = None,
            annotationComplete: Optional[Dict[str, str]] = None,
            imageLabels: Optional[List[str]] = None,
            **kwargs: Any,
        ) -> Dict[str, Any]:
            if metadata is not None:
                tile["metadata"].update(metadata)
            if annotationUID is not None:
                tile["annotationUID"].update(annotationUID)
            if auditUID is not None:
                tile["auditUID"].update(auditUID)
            if annotationComplete is not None:
                if "annotationComplete" not in tile:
                    tile["annotationComplete"] = {}
                tile["annotationComplete"].update(annotationComplete)
            if imageLabels is not None:
                tile["imageLabels"] = imageLabels
            return tile

        logger.info("updating gallery's tile..")

        try:
            gallery = self._get_gallery()

            tile_index = self._find_gallery_tile(gallery, item_uid)

            gallery[tile_index] = update_tile({**gallery[tile_index]}, **tile_data)

            self._set_gallery(gallery)
        except Exception as e:
            logger.error(f"Error while updating a gallery's tile: {e}")

        logger.info("updated gallery's tile")

    def upload_image(
        self,
        account: Account,
        project_uid: str,
        name: str,
        image: Union[str, Image.Image],
        image_labels: List[str] = [],
        metadata: Dict[str, Any] = {},
    ) -> Union[str, None]:
        """Create, encrypt and upload a new item to the STORE project.

        Parameters
        ----------
        account: Account
            Instance of the main Etebase class.
        project_uid: str
            Project's uid.
        name: str
            Name of the new item.
        image: Union[str, Image.Image]
            2D image to upload to the new item.
        image_labels: List[str]
            Image labels (optional).
        metadata: Dict
            Metadata (optional).
        -------
        item_uid: Union[str, None]
            New image item's uid.
        """

        logger.info("creating new image item...")

        self.update_project_data(account, project_uid)

        # process the input image
        image_data = self._process_image_data(image)
        if image_data is None:
            return None

        # create a new gliff.image item and upload it to the project
        ctime = self.get_current_time()
        item_metadata = {
            "type": "gliff.image",
            "imageName": name,
            "createdTime": ctime,
            "modifiedTime": ctime,
        }

        item = self.project.item_mng.create(item_metadata, image_data["encoded_image"])
        self.project.item_mng.transaction([item])

        logger.success("image item created.")

        # create a new tile and add this to the project's content (or gallery)
        new_tile = self._create_new_tile(
            item.uid,
            image_data["thumbnail"],
            image_labels,
            metadata={
                "imageName": name,
                "width": image_data["width"],
                "height": image_data["height"],
                **metadata,
            },
        )

        self._create_gallery_tile(new_tile)

        return item.uid

    def update_metadata_and_labels(
        self,
        account: Account,
        project_uid: str,
        item_uid: str,
        image_labels: Union[List[str], None] = None,
        metadata: Dict[str, Any] = {},
    ) -> None:
        """Create, encrypt and upload a new item to the STORE project.

        Parameters
        ----------
        account
            Instance of the main Etebase class.
        project_uid: str
            Project's uid.
        item_uid: str
            Image item's uid.
        image_labels: List[str]
            Image labels (optional).
        metadata: Dict
            Metadata (optional).
        """

        logger.info("updating image item's metadata...")

        if not metadata and not image_labels:
            return None

        self.update_project_data(account, project_uid)

        item = self.get_project_item(account, project_uid, item_uid)

        item.meta = {
            **item.meta,
            "modifiedTime": self.get_current_time(),
        }

        self.project.item_mng.transaction([item])

        tile_data = self._create_tile_update(image_labels=image_labels, metadata=metadata)
        self._update_gallery_tile(item_uid, tile_data)

        logger.success("metadata updated.")

    def get_image_data(self, account: Account, project_uid: str, item_uid: str) -> Union[List[List[Image.Image]], None]:
        """Get the image data from an image item.

        Parameters
        ----------
        account: Account
            Instance of the main Etebase class.
        project_uid: str
            Project's uid.
        item_uid: str
            Annotation item's uid.
        Returns
        -------
        image_data: Union[List[List[Image.Image]], None]
            Image item's decoded content.
        """

        self.update_project_data(account, project_uid)

        logger.info(f"fetching item's image data, uid: {item_uid}...")

        try:
            item = self.get_project_item(account, project_uid, item_uid)
            decoded_content = self.decode_content(item.content)

            image_data: List[List[Image.Image]] = []
            for i_slice in range(len(decoded_content)):
                image_data.append([])
                for i_channel in range(len(decoded_content[i_slice])):
                    image_data[i_slice].append(self.base64_to_pil_image(decoded_content[i_slice][i_channel]))

            logger.success("image data fetched.")
            return image_data
        except Exception as e:
            logger.error(f"Error while fetching an item's image data: {e}")
        return None

    def get_metadata_and_labels(self, account: Account, project_uid: str, item_uid: str) -> Union[Dict[str, Any], None]:
        """Retrieve an image's metadata and image-wise labels.

        Parameters
        ----------
        account: Account
            Instance of the main Etebase class.
        project_uid: str
            Project's uid.
        item_uid: str
            Image item's uid.
        Returns
        -------
        metadata: Dict
            Metadata.
        image_labels: List[str]
            Image labels.
        """

        self.update_project_data(account, project_uid)

        try:
            gallery = self._get_gallery()

            index = self._find_gallery_tile(gallery, item_uid)

            return gallery[index]["metadata"], gallery[index]["imageLabels"]

        except Exception as e:
            logger.error(f"error while retrieving image item's metadata: {e}")
        return None

    def _get_annotation_uid(
        self, account: Account, project_uid: str, image_item_uid: str, username: str
    ) -> Union[str, None]:
        """Check whether there exists an annotation made by a user with corresponding username and for an image
        item with uid equal to image_item_uid and return the annotation item's uid.

        Parameters
        ----------
        account: Account
            Instance of the main Etebase class.
        project_uid: str
            Project's uid.
        image_item_uid: str
            Image item's uid.
        username: str
            Identifier for the user who makes the annotation.
        Returns
        -------
        item_uid: Union[str, None]
            Annotation item's uid.
        """
        self.update_project_data(account, project_uid)

        gallery = self._get_gallery()

        item_uid = None
        for tile in gallery:
            if tile["id"] == image_item_uid:
                if username in tile["annotationUID"]:
                    item_uid = tile["annotationUID"][username]
                    break
        return item_uid

    def _create_annotation_item(
        self,
        account: Account,
        project_uid: str,
        image_item_uid: str,
        username: str,
        annotations: List[Dict[str, Any]],
        metadata: Dict[str, Any] = {},
    ) -> str:
        """Create, encrypt and upload a new item to the STORE project.

        Parameters
        ----------
        account
            Instance of the main Etebase class.
        project_uid: str
            Project's uid.
        image_item_uid: str
            Image item's uid.
        username: str
            Identifier for the user who makes the annotation.
        annotations: List[Dict]
            Annotation data.
        metadata: Dict
            Metadata (optional).
        Returns
        -------
        item_uid: str
            New annotation item's uid.
        """

        logger.info("creating new annotation item...")

        self.update_project_data(account, project_uid)

        # create a new gliff.annotation item and store it in the project
        ctime = self.get_current_time()
        item_metadata = {
            "type": "gliff.annotation",
            "createdTime": ctime,
            "modifiedTime": ctime,
            "isComplete": False,
        }

        item_content = self.encode_content(annotations)

        item: Item = self.project.item_mng.create(item_metadata, item_content)
        self.project.item_mng.transaction([item])

        logger.success("annotation item created.")

        # update the info stored in the corresponding gallery tile
        tile_data = self._create_tile_update(
            metadata=metadata, annotation_uid={username: item.uid}, annotation_complete={username: False}
        )
        self._update_gallery_tile(image_item_uid, tile_data)

        return item.uid

    def _update_annotation_item(
        self,
        account: Account,
        project_uid: str,
        image_item_uid: str,
        annotation_item_uid: str,
        annotations: List[Dict[str, Any]],
        metadata: Dict[str, Any] = {},
    ) -> str:
        """Create, encrypt and upload a new item to the STORE project.

        Parameters
        ----------
        account
            Instance of the main Etebase class.
        project_uid: str
            Project's uid.
        image_item_uid: str
            Image item's uid.
        annotation_item_uid: str
            Uid for annotation to update.
        annotations: List[Dict]
            Annotations data.
        metadata: Dict
            Metadata (optional).

        Returns
        -------
        item_uid: str
            Annotation item's uid.
        """

        self.update_project_data(account, project_uid)

        logger.info(f"updating annotation item, uid: {annotation_item_uid}...")

        item = self.get_project_item(account, project_uid, annotation_item_uid)

        # if the last annotation is empty, remove it
        prev_annotations = self.decode_content(item.content)
        if len(prev_annotations) > 0 & self.is_empty_annotation(prev_annotations[-1]):
            prev_annotations.pop()

        # update the annotation item and store and store the changes
        item.meta = {**item.meta, "modifiedTime": self.get_current_time()}

        item.content = self.encode_content([*prev_annotations, *annotations])

        self.project.item_mng.transaction([item])

        logger.success("annotation item updated.")

        # if required, update the metadata
        if metadata:
            tile_data = self._create_tile_update(metadata=metadata)
            self._update_gallery_tile(image_item_uid, tile_data)

        return item.uid

    def upload_annotation(
        self,
        account: Account,
        project_uid: str,
        image_item_uid: str,
        username: str,
        annotations: List[Dict[str, Any]],
        metadata: Dict[str, Any] = {},
    ) -> str:
        """Encrypt and upload an annotation to the STORE project.

        Parameters
        ----------
        account
            Instance of the main Etebase class.
        project_uid: str
            Project's uid.
        image_item_uid: str
            Image item's uid.
        username: str
            Identifier for the user who makes the annotation.
        annotations: List[Dict]
            Annotations data.
        metadata: Dict
            Metadata (optional).
        Returns
        -------
        item_uid: str
            Annotation item's uid.
        """

        annotation_item_uid = self._get_annotation_uid(account, project_uid, image_item_uid, username)

        if annotation_item_uid is None:
            # create new annotation item
            annotation_item_uid = self._create_annotation_item(
                account, project_uid, image_item_uid, username, annotations=annotations, metadata=metadata
            )
        else:
            # update existing annotation item
            self._update_annotation_item(
                account, project_uid, image_item_uid, annotation_item_uid, annotations=annotations, metadata=metadata
            )
        return annotation_item_uid

    def get_annotations(
        self, account: Account, project_uid: str, image_item_uid: str, username: str
    ) -> Union[List[Dict[str, Any]], None]:
        """Get all the annotations from an annotation item.

        Parameters
        ----------
        account: Account
            Instance of the main Etebase class.
        project_uid: str
            Project's uid.
        image_item_uid: str
            Image item's uid.
        username: str
            Identifier for the user who makes the annotation.
        Returns
        -------
        annotations: Union[List[Dict], None]
            Annotations data.
        """
        self.update_project_data(account, project_uid)

        try:
            annotation_item_uid = self._get_annotation_uid(account, project_uid, image_item_uid, username)
            if annotation_item_uid is not None:
                item = self.get_project_item(account, project_uid, annotation_item_uid)
                return self.decode_content(item.content)
        except Exception as e:
            logger.error(f"Error while fetching an item's annotations: {e}")
        return None
