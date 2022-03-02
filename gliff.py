import base64
import json
import time
from decouple import config, UndefinedValueError
from loguru import logger
from etebase import Client, Account, Collection, Item
from PIL import Image
from io import BytesIO
from typing import Union, Optional, Any, List, Dict
import numpy as np


def get_value(env_variable: str) -> Any:
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
        raise UndefinedValueError("{} not found.".format(env_variable))


def base64_to_pil_image(img_base64: Union[str, bytes]) -> Image.Image:
    """Convert a base64-encoded image into a PIL Image object"""

    img_bytes = base64.b64decode(img_base64)
    img_file = BytesIO(img_bytes)
    return Image.open(img_file).convert("RGB")


def pil_to_base64_image(img_pil: Image.Image, is_thumbnail: Optional[bool] = False) -> str:
    """Convert a PIL Image object to a base64-encoded image (in bytes)"""

    img_file = BytesIO()
    img_pil.save(img_file, format="PNG")
    img_bytes = img_file.getvalue()
    img_base64 = base64.b64encode(img_bytes).decode()
    if is_thumbnail:
        img_base64 = "data:image/png;base64,{}".format(img_base64)
    return img_base64


def _get_thumbnail_from_pil_image(img_pil: Image.Image) -> str:
    """Get base64-encoded thumbnail (in bytes) from PIL image"""

    size = 128, 128
    img_pil.thumbnail(size, Image.ANTIALIAS)
    return pil_to_base64_image(img_pil, True)


def decode_content(content: bytes) -> Any:
    """Extract and decode collection's or item's content, from binary to Dict."""
    try:
        return json.loads(content.decode())
    except json.JSONDecodeError as e:
        logger.warning("Error while accessing the collection's content: {}.".format(e))


def encode_content(decoded_content: Any) -> bytes:
    """Encode collection's or item's content, from Dict to binary."""
    return json.dumps(decoded_content, separators=(",", ":")).encode()


def get_current_time() -> int:
    return int(round(time.time() * 1000))


def is_empty_annotation(annotation: Dict[str, Any]) -> bool:
    return (
        (len(annotation["spline"]["coordinates"]) == 0)
        & (len(annotation["brushStrokes"]) == 0)
        & (annotation["boundingBox"]["coordinates"]["topLeft"]["x"] is None)
    )


def create_brush_stroke(
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
    return {
        "coordinates": coordinates,
        "spaceTimeInfo": spaceTimeInfo,
        "brush": brush,
    }


def create_annotation(
    toolbox: str,
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
    return {
        "toolbox": toolbox,
        "labels": labels,
        "spline": spline,
        "boundingBox": bounding_box,
        "brushStrokes": brush_strokes,
        "parameters": parameters,
    }


def _get_image_data(image: Union[str, Image.Image]) -> Union[None, Dict[str, Any]]:
    """Create, encrypt and upload a new item to the STORE collection.

    Parameters
    ----------
    image: PIL.Image.Image or str
        Image uploaded to the new item.
    Returns
    -------
    image_data: Dict or None
        A dictionary that includes image width, height, thumbnail and the ecoded image.
    """

    # checks image type and process image
    if type(image) == Image.Image:
        image_pil = image
        image = pil_to_base64_image(image)
    elif isinstance(image, str):
        image_pil = base64_to_pil_image(image)
    else:
        logger.error("image should be of type PIL.Image.Image or str")
        return None

    width, height = image_pil.size
    return {
        "width": width,
        "height": height,
        "thumbnail": _get_thumbnail_from_pil_image(image_pil),
        "encoded_image": encode_content([[image]]),
    }


def _get_collection_and_manager(account: Account, col_uid: int, col_data: Dict[str, Any]) -> None:
    """Get collection manager and collection.

    Parameters
    ----------
    account: Account
        Instance of the main etebase class.
    col_uid: int
        Collection uid.
    col_data: Dict
        Etebase collection data (i.e., collection manager, collection, item manager).
    """

    logger.info("fetching collection manager...")
    col_data["col_mng"] = account.get_collection_manager()
    logger.info("collection manager fetched.")

    logger.info("fetching collection...")
    col_data["collection"] = col_data["col_mng"].fetch(col_uid)
    logger.info("collection fetched.")


def _get_all_col_data(account: Account, col_uid: int, col_data: Dict[str, Any] = {}) -> None:
    """Get etebase item manager for a given collection with uid == col_uid.

    Parameters
    ----------
    account: Account
        Instance of the main etebase class.
    col_uid: int
        Collection uid.
    col_data: Dict
        Etebase collection data (i.e., collection manager, collection, item manager).
    """
    if "col_mng" or "collection" not in col_data:
        _get_collection_and_manager(account, col_uid, col_data)

    if "item_mng" not in col_data:
        logger.info("fetching item manager...")
        col_data["item_mng"] = col_data["col_mng"].get_item_manager(col_data["collection"])
        logger.info("item manager fetched.")


def login(username: str, password: str, server_url: str) -> Any:
    """Log in to STORE.

    Parameters
    ----------
    username: str
        Plugin's user's username.
    password: str
        Plugin's user's password.
    server_url: str
        Server URL.
    Returns
    -------
    account: Account
        Instance of the main etebase class.
    """

    logger.info("logging in to STORE...")
    client = Client("client-name", server_url)
    account = Account.login(
        client,
        username,
        password,
    )
    logger.success("logged in.")

    _accept_pending_invitations(account)

    return account


def logout(account: Account) -> None:
    """Log out of STORE.

    Parameters
    ----------
    account: Account
        Instance of the main etebase class.
    """

    logger.info("logging out...")
    account.logout()
    logger.success("logged out.")


def _accept_pending_invitations(account: Account) -> None:
    """Accept all pending invitations to join a STORE collection.

    Parameters
    ----------
    account: Account
        Instance of the main etebase class.
    """

    invit_mng = account.get_invitation_manager()

    invitations = invit_mng.list_incoming()
    logger.info("pending invitations: {}".format(invitations))

    for invitation in list(invitations.data):

        invit_mng.accept(invitation)
        logger.success("invitations accepted.")


def _leave_collection(account: Account, col_uid: int, col_data: Dict[str, Any] = {}) -> None:
    """Leave a collection.

    Parameters
    ----------
    account: Account
        Instance of the main etebase class.
    col_uid: int
        Collection uid.
    col_data: Dict
        Etebase data (i.e., collection manager, collection, item manager)
    """
    _get_collection_and_manager(account, col_uid, col_data)

    logger.info("leaving collection {}...".format(col_uid))
    memeber_mng = col_data["col_mng"].get_member_manager(col_data["collection"])
    memeber_mng.leave()
    logger.info("left collection.".format(col_uid))


def get_collection_item(account: Account, col_uid: int, item_uid: int, col_data: Dict[str, Any] = {}) -> Item:
    """Retrieve a collection's item.

    Parameters
    ----------
    account: Account
        Instance of the main etebase class.
    col_uid: int
        Collection uid.
    item_uid: int
        Item uid.
    col_data:
        Etebase data (i.e., collection manager, collection, item manager)
    Returns
    -------
    item: Item
        Collection's item
    """

    _get_all_col_data(account, col_uid, col_data)

    try:
        logger.info("fetching item, uid: {}...".format(item_uid))
        item = col_data["item_mng"].fetch(item_uid)
        logger.info("item fetched.")
        return item
    except Exception as e:
        logger.error("error while fetching image: {}.".format(e))


def _create_gallery_tile(col_data: Any, item_uid: int, thumbnail: str, tile_data: Dict[str, Any] = {}) -> None:
    """Create, ecrypt and upload a new tile to the STORE collection.

    Parameters
    ----------
    col_data:
        Etebase collection data (i.e., collection manager, collection, item manager).
    item_uid: int
        Item uid.
    thumbnail: string
        Base64-encoded image's thumbnail.
    tile_data: Dict
        Custom tile data key-value pairs (optional).
    """

    logger.info("updating collection's content..")

    try:
        gallery = _get_gallery(col_data["collection"])

        if "metadata" in tile_data:
            metadata = tile_data.pop("metadata")
        else:
            metadata = {}

        new_gallery_tile = {
            "id": item_uid,
            "thumbnail": thumbnail,
            "imageLabels": [],
            "assignees": [],
            "metadata": metadata,
            "imageUID": item_uid,
            "annotationUID": {},
            "auditUID": {},
            "annotationComplete": {},
            **tile_data,
        }

        gallery.append(new_gallery_tile)

        _set_gallery(col_data["col_mng"], col_data["collection"], gallery)
    except Exception as e:
        logger.error("Error while creating a gallery's tile: {}".format(e))


def _get_gallery(collection: Collection) -> Dict[str, Any]:
    return decode_content(collection.content)


def _find_gallery_tile(gallery: List[Dict[str, Any]], id: str) -> Union[int, None]:
    """Get the index for the gallery tile corresponding to the image item with
    uid equal to the galler's id (or equal to the imageUID field)."""
    for i, tile in enumerate(gallery):
        if tile["id"] == id:
            return i
    return None


def _set_gallery(col_mng, collection: Collection, gallery: List[Dict[str, Any]]) -> None:
    collection.content = encode_content(gallery)
    col_mng.transaction(collection)


def _update_gallery_tile(col_data: Any, item_uid: int, tile_data: Dict[str, Any] = {}) -> None:
    """Update a tile in the STORE collection.
    Parameters
    ----------
    col_data:
        Etebase data (i.e., collection manager, collection, item manager)
    item_uid: int
        Item uid (the item is of type gliff.image).
    tile_data: Dict (optional)
    """

    def update_tile(
        tile: Dict[str, Any],
        metadata: Optional[Dict[str, Any]] = None,
        annotationUID: Optional[Dict[str, str]] = None,
        annotationComplete: Optional[Dict[str, str]] = None,
        imageLabels: Optional[List[str]] = None,
        **kwargs: Any
    ) -> Dict[str, Any]:
        if metadata is not None:
            tile["metadata"].update(metadata)
        if annotationUID is not None:
            tile["annotationUID"].update(annotationUID)
        if annotationComplete is not None:
            tile["annotationComplete"].update(annotationComplete)
        if imageLabels is not None:
            tile["imageLabels"] = imageLabels
        return tile

    logger.info("updating gallery's tile..")

    try:
        gallery = _get_gallery(col_data["collection"])

        tile_index = _find_gallery_tile(gallery, item_uid)

        gallery[tile_index] = update_tile({**gallery[tile_index]}, **tile_data)

        _set_gallery(col_data["col_mng"], col_data["collection"], gallery)
    except Exception as e:
        logger.error("Error while updating a gallery's tile: {}".format(e))

    logger.info("updated gallery's tile")


def create_image_item(
    account: Account,
    col_uid: int,
    name: str,
    image: Union[str, Image.Image],
    image_labels: List[str] = [],
    metadata: Dict[str, Any] = {},
    col_data: Dict[str, Any] = {},
) -> Union[int, None]:
    """Create, encrypt and upload a new item to the STORE collection.

    Parameters
    ----------
    account: Account
        Instance of the main etebase class.
    col_uid: int
        Collection uid.
    name: string
        Name of the new item.
    image: Union[str, Image.Image]
        2D image to upload to the new item.
    image_labels: List[str]
        Image labels (optional).
    metadata: Dict
        Metadata to be stored inside the new item (optional).
    col_data:
        Etebase collection data (i.e., collection manager, collection, item manager).
    -------
    item_uid: Union[int, None]
        New image item's uid.
    """

    logger.info("creating new image item...")

    _get_all_col_data(account, col_uid, col_data)

    image_data = _get_image_data(image)
    if image_data is None:
        return None

    # place the image in the expected array structure and stringify the result
    item_content = image_data["encoded_image"]

    ctime = get_current_time()
    item_metadata = {
        "type": "gliff.image",  # STORE image item type
        "imageName": name,  # check if this has changed
        "createdTime": ctime,
        "modifiedTime": ctime,
    }

    tile_data = {
        "metadata": {
            "imageName": name,
            "width": image_data["width"],
            "height": image_data["height"],
            **metadata,
        },
        "imageLabels": image_labels,
    }

    # create a new item and upload it to the collection
    item = col_data["item_mng"].create(item_metadata, item_content)
    col_data["item_mng"].transaction([item])
    logger.success("image item created.")

    # add the new tile to the collection's content
    _create_gallery_tile(
        col_data,
        item.uid,
        image_data["thumbnail"],
        tile_data,
    )

    return item.uid


def update_image_metadata(
    account: Account,
    col_uid: int,
    item_uid: int,
    image_labels: List[str] = [],
    metadata: Dict[str, Any] = {},
    col_data: Dict[str, Any] = {},
) -> None:
    """Create, encrypt and upload a new item to the STORE collection.

    Parameters
    ----------
    account
        Instance of the main etebase class.
    col_uid: int
        Collection uid.
    item_uid: int
        Image item's uid.
    image_labels: List[str]
        Image labels (optional).
    metadata: Dict
        New metadata to overwrite existing metadata (optional).
    col_data: Dict
        Etebase collection data (i.e., collection manager, collection, item manager).
    """

    logger.info("updating image item's metadata...")

    _get_all_col_data(account, col_uid, col_data)

    # get existing item
    item = get_collection_item(account, col_uid, item_uid, col_data)

    # update image item's time modified (stored in the item's metadata)
    item.meta = {
        **item.meta,
        "modifiedTime": get_current_time(),
    }

    col_data["item_mng"].transaction([item])

    tile_data = {"metadata": metadata, "imageLabels": image_labels}

    # update image item metadata (stored in the collection's content)
    _update_gallery_tile(col_data, item_uid, tile_data)

    logger.success("metadata updated.")


def get_item_image_data(account: Account, col_uid: int, item_uid: int, col_data: Dict[str, Any] = {}) -> Image.Image:
    """Get the image data from an image item.

    Parameters
    ----------
    account: Account
        Instance of the main etebase class.
    col_uid: int
        Collection uid.
    item_uid: int
        Annotation item's uid.
    col_data: Dict
        Etebase collection data (i.e., collection manager, collection, item manager).
    Returns
    -------
    image_data: Image.Image
        Image item's decoded content.
    """

    _get_all_col_data(account, col_uid, col_data)

    logger.info("fetching item's image data, uid: {}...".format(item_uid))

    try:
        item = get_collection_item(account, col_uid, item_uid, col_data)
        decoded_content = decode_content(item.content)

        image_data = []
        for i_slice in range(len(decoded_content)):
            image_data.append([])
            for i_channel in range(len(decoded_content[i_slice])):
                image_data[i_slice].append(base64_to_pil_image(decoded_content[i_slice][i_channel]))

        logger.success("image data fetched.")
        return image_data
    except Exception as e:
        logger.error("Error while fetching an item's image data: {}".format(e))


def get_image_metadata(account: Account, col_uid: int, item_uid: int, col_data: Dict[str, Any] = {}) -> Dict[str, Any]:
    """Retrieve metadata for an image item.

    Parameters
    ----------
    account: Account
        Instance of the main etebase class.
    col_uid: int
        Collection uid.
    item_uid: int
        Image item's uid.
    col_data:
        Etebase collection data (i.e., collection manager, collection, item manager).
    Returns
    -------
    metadata
        Image item's metadata.
    """

    _get_all_col_data(account, col_uid, col_data)

    included_keys = ["metadata", "imageLabels"]

    try:
        gallery = _get_gallery(col_data["collection"])

        index = _find_gallery_tile(gallery, item_uid)

        return {key: gallery[index][key] for key in set(included_keys)}
    except Exception as e:
        logger.error("error while retrieving image item's metadata: {}".format(e))


def get_annotation_uid(
    account: Account, col_uid: int, image_item_uid: int, username: str, col_data: Dict[str, Any] = {}
) -> Union[int, None]:
    """Check whether there exists an annotation made by a user with corresponding username and for an image
    item with uid equal to image_item_uid and return the annotation item's uid.

    Parameters
    ----------
    account: Account
        Instance of the main etebase class.
    col_uid: int
        Collection uid.
    image_item_uid: int
        Uid for corresponding image item.
    username: str
        Identifier for the user who makes the annotation.
    col_data:
        Etebase collection data (i.e., collection manager, collection, item manager).
    Returns
    -------
    item_uid: Union[int, None]
        Annotation item's uid.
    """
    _get_collection_and_manager(account, col_uid, col_data)

    gallery = _get_gallery(col_data["collection"])

    item_uid = None
    for tile in gallery:
        if tile["id"] == image_item_uid:
            if username in tile["annotationUID"]:
                item_uid = tile["annotationUID"][username]
                break
    return item_uid


def create_annotation_item(
    account: Account,
    col_uid: int,
    image_item_uid: int,
    username: str,
    annotations: List[Dict[str, Any]],
    metadata: Dict[str, Any] = {},
    col_data: Dict[str, Any] = {},
) -> int:
    """Create, encrypt and upload a new item to the STORE collection.

    Parameters
    ----------
    account
        Instance of the main etebase class.
    col_uid: int
        Collection uid.
    image_item_uid: int
        Uid for corresponding image item.
    username: str
        Identifier for the user who makes the annotation.
    annotation: PIL.Image.Image or str
        Annotation to upload to the new item.
    metadata: Dict
        Metadata to be stored inside the new item (optional).
    col_data:
        Etebase collection data (i.e., collection manager, collection, item manager).
    Returns
    -------
    item_uid: int
        New annotation item's uid.
    """

    logger.info("creating new annotation item...")

    _get_all_col_data(account, col_uid, col_data)

    # defined item's content
    item_content = encode_content(annotations)

    # defined item's metadata
    ctime = get_current_time()
    item_metadata = {
        "type": "gliff.annotation",
        "createdTime": ctime,
        "modifiedTime": ctime,
        "isComplete": False,
    }

    # create a new item and store it in the collection
    item = col_data["item_mng"].create(item_metadata, item_content)
    col_data["item_mng"].transaction([item])

    logger.success("annotation item created.")

    # TODO: add audit
    tile_data = {
        "metadata": metadata,
        "annotationUID": {username: item.uid},
        "annotationComplete": {username: False},
    }
    _update_gallery_tile(col_data, image_item_uid, tile_data)

    return item.uid


def update_annotation_item(
    account: Account,
    col_uid: int,
    image_item_uid: int,
    username: str,
    annotations: List[Dict[str, Any]],
    metadata: Dict[str, Any] = {},
    col_data: Dict[str, Any] = {},
    annotation_item_uid: Optional[int] = None,
):
    """Create, encrypt and upload a new item to the STORE collection.

    Parameters
    ----------
    account
        Instance of the main etebase class.
    col_uid: int
        Collection uid.
    image_item_uid: int
        Image item's uid.
    username: str
        Identifier for the user who makes the annotation.
    annotations: Dict
        Annotation to upload to the new item.
    metadata: Dict
        Metadata to be stored inside the new item (optional).
    col_data:
        Etebase collection data (i.e., collection manager, collection, item manager).
    annotation_item_uid: Optional[int]
        Uid for annotation to update (optional).
    Returns
    -------
    item_uid: int
        Annotation item's uid.
    """

    _get_all_col_data(account, col_uid, col_data)

    if annotation_item_uid is None:
        annotation_item_uid = get_annotation_uid(account, col_uid, image_item_uid, username, col_data)

    logger.info("updating annotation item, uid: {}...".format(annotation_item_uid))

    item = get_collection_item(account, col_uid, annotation_item_uid, col_data=col_data)

    # remove last annotation if empty
    prev_annotations = decode_content(item.content)
    if len(prev_annotations) > 0 & is_empty_annotation(prev_annotations[-1]):
        prev_annotations.pop()

    # update item's metadata
    item.meta = {**item.meta, "modifiedTime": get_current_time()}

    # update item's content
    item.content = encode_content([*prev_annotations, *annotations])

    # save changes
    col_data["item_mng"].transaction([item])

    logger.success("annotation item updated.")

    tile_data = {
        "metadata": metadata,
    }
    _update_gallery_tile(col_data, image_item_uid, tile_data)

    return item.uid


def get_item_annotations(account: Account, col_uid: int, item_uid: int, col_data: Dict[str, Any] = {}) -> Any:
    """Get the annotations from an annotation item.

    Parameters
    ----------
    account: Account
        Instance of the main etebase class.
    col_uid: int
        Collection uid.
    item_uid: int
        Annotation item's uid.
    col_data:
        Etebase collection data (i.e., collection manager, collection, item manager).
    Returns
    -------
    metadata
        Image item's metadata.
    """
    _get_all_col_data(account, col_uid, col_data)

    try:
        item = get_collection_item(account, col_uid, item_uid, col_data)
        return decode_content(item.content)
    except Exception as e:
        logger.error("Error while fetching an item's annotations: {}".format(e))
