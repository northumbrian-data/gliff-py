import base64
import json
import time
from unicodedata import numeric
from decouple import config, UndefinedValueError
from loguru import logger
from etebase import Client, Account
from PIL import Image
from io import BytesIO
from typing import Union, Optional, Any


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


def _decode_content(content: bytes) -> Any:
    """Extract and decode collection's or item's content, from binary to dict."""
    return json.loads(content.decode())


def _encode_content(decoded_content: Any) -> bytes:
    """Encode collection's or item's content, from dict to binary."""
    return json.dumps(decoded_content, separators=(",", ":")).encode()


def _get_current_time() -> int:
    return int(round(time.time() * 1000))


def is_empty_annotation(annotation: dict[str, Any]) -> bool:
    return (
        (len(annotation["spline"]["coordinates"]) == 0)
        & (len(annotation["brushStrokes"]) == 0)
        & (annotation["boundingBox"]["coordinates"]["topLeft"]["x"] is None)
    )


def create_brush_stroke(
    coordinates: list[Union[int, float]],
    spaceTimeInfo: Optional[dict[str, Any]] = {
        "z": 0,
        "t": 0,
    },
    brush: Optional[dict[str, Any]] = {
        "radius": 0.5,
        "type": "paint",
        "color": "rgba(170, 0, 0, 0.5)",
        "is3D": False,
    },
) -> Optional[dict[str, Any]]:
    return {
        "coordinates": coordinates,
        "spaceTimeInfo": spaceTimeInfo,
        "brush": brush,
    }


def create_annotation(
    toolbox: str,
    labels: list[str] = [],
    spline: Optional[dict[str, Any]] = {
        "coordinates": [],
        "spaceTimeInfo": {"z": 0, "t": 0},
        "isClosed": False,
    },
    bounding_box: Optional[dict[str, Any]] = {
        "coordinates": {
            "topLeft": {"x": None, "y": None},
            "bottomRight": {"x": None, "y": None},
        },
        "spaceTimeInfo": {"z": 0, "t": 0},
    },
    brush_strokes: Optional[list[Optional[dict[str, Any]]]] = [],
    parameters: Optional[dict[str, Any]] = {},
) -> dict[str, Any]:
    return {
        "toolbox": toolbox,
        "labels": labels,
        "spline": spline,
        "boundingBox": bounding_box,
        "brushStrokes": brush_strokes,
        "parameters": parameters,
    }


def _get_image_data(image: Union[str, Image.Image]) -> Union[None, dict[str, Any]]:
    """Create, encrypt and upload a new item to the STORE collection.

    Parameters
    ----------
    image: PIL.Image.Image or str
        Image uploaded to the new item.
    Returns
    -------
    image_data: dict or None
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
        "encoded_image": _encode_content([[image]]),
    }


def _get_collection_and_manager(etebase: Any, col_uid: int, etedata: dict[str, Any] = {}) -> dict[str, Any]:
    """Get collection manager and collection.

    Parameters
    ----------
    etebase
        Instance of the main etebase class.
    col_uid: int
        Collection uid.
    etedata: dict
        Etebase data (i.e., collection manager, collection, item manager)
    Returns
    -------
    etedata: dict
        Updated etebase data dictionary
    """

    logger.info("fetching collection manager and collection...")
    col_mng = etebase.get_collection_manager()
    collection = col_mng.fetch(col_uid)
    logger.info("fetched collection manager and collection.")
    etedata.update({"col_mng": col_mng, "collection": collection})

    return etedata


def _get_all_etedata(etebase: Any, col_uid: int, etedata: dict[str, Any] = {}) -> Any:
    """Get etebase item manager for a given collection with uid == col_uid.

    Parameters
    ----------
    etebase
        Instance of the main etebase class.
    col_uid: int
        Collection uid.
    etedata: dict
        Etebase data (i.e., collection manager, collection, item manager)
    Returns
    -------
    etedata: dict
        Updated etebase data dictionary
    """
    if "col_mng" not in etedata:
        etedata.update(_get_collection_and_manager(etebase, col_uid))
    elif "collection" not in etedata:
        logger.info("fetching collection...")
        etedata.update({"collection": etedata["col_mng"].fetch(col_uid)})
        logger.info("collection fetched.")

    if "item_mng" not in etedata:
        logger.info("fetching item manager...")
        etedata.update({"item_mng": etedata["col_mng"].get_item_manager(etedata["collection"])})
        logger.info("fetched item manager.")

    return etedata


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
    etebase
        Instance of the main etebase class.
    """

    logger.info("logging in to STORE...")
    client = Client("client-name", server_url)
    etebase = Account.login(
        client,
        username,
        password,
    )
    logger.success("logged in to STORE")

    _accept_pending_invitations(etebase)

    return etebase


def logout(etebase: Any) -> None:
    """Log out of STORE."""

    logger.info("logging out...")
    etebase.logout()
    logger.success("logged out")


def _accept_pending_invitations(etebase: Any) -> None:
    """Accept all pending invitations to join a STORE collection.

    Parameters
    ----------
    etebase
        Instance of the main etebase class.
    """

    invit_mng = etebase.get_invitation_manager()

    invitations = invit_mng.list_incoming()
    logger.info("pending invitations: {}".format(invitations))

    for invitation in list(invitations.data):
        # TODO: verify that the public key is indeed the pubkey you expect

        invit_mng.accept(invitation)
        logger.success("accepted invitation {}.".format(invitation))


def _leave_collection(etebase: Any, col_uid: int, etedata: dict[str, Any] = {}) -> None:
    """Leave a collection.

    Parameters
    ----------
    etebase
        Instance of the main etebase class.
    col_uid: int
        Collection uid.
    etedata: dict
        Etebase data (i.e., collection manager, collection, item manager)
    """

    logger.info("leaving collection {}...".format(col_uid))
    etedata = _get_collection_and_manager(etebase, col_uid, etedata)
    memeber_mng = etedata["col_mng"].get_member_manager(etedata["collection"])
    memeber_mng.leave()
    logger.info("left collection {}.".format(col_uid))


def get_collection_item(etebase: Any, col_uid: int, item_uid: int, etedata: dict[str, Any] = {}) -> Any:
    """Retrieve a collection's item.

    Parameters
    ----------
    etebase:
        Instance of the main etebase class.
    col_uid: int
        Collection uid.
    item_uid: int
        Item uid.
    etedata:
        Etebase data (i.e., collection manager, collection, item manager)
    Returns
    -------
    item
    """

    etedata = _get_all_etedata(etebase, col_uid, etedata)

    try:
        logger.info("fetching item {}...".format(item_uid))
        item = etedata["item_mng"].fetch(item_uid)
        logger.info("fetched item {}.".format(item_uid))
    except Exception as e:
        logger.error("Error while fetching image: {}.".format(e))
        return

    return item


def _create_gallery_tile(etedata: Any, item_uid: int, thumbnail: str, metadata: dict[str, Any] = {}) -> None:
    """Create, ecrypt and upload a new tile to the STORE collection.

    Parameters
    ----------
    etedata:
        Etebase data (i.e., collection manager, collection, item manager)
    item_uid: int
        Item uid.
    thumbnail: string
        Base64-encoded image's thumbnail.
    metadata: dict
        Metadata key-value pairs (optional).
    """

    logger.info("updating collection's content..")

    # get decoded collection content
    gallery = _decode_content(etedata["collection"].content)

    # defined a gallery tile for the new item
    gallery_tile = {
        "id": item_uid,
        "thumbnail": thumbnail,
        "imageLabels": [],
        "assignees": [],
        "metadata": metadata,
        "imageUID": item_uid,
        "annotationUID": {},
        "auditUID": {},
        "annotationComplete": {},
    }

    # add new tile
    gallery.append(gallery_tile)

    # replace old collection's content with new one
    etedata["collection"].content = _encode_content(gallery)

    # save changes
    etedata["col_mng"].transaction(etedata["collection"])
    logger.success("updated collection's content")


def _update_gallery_tile(etedata: Any, item_uid: int, tile_data: dict[str, Any] = {}) -> None:
    """Update a tile in the STORE collection.
    Parameters
    ----------
    etedata:
        Etebase data (i.e., collection manager, collection, item manager)
    item_uid: int
        Item uid (the item is of type gliff.image).
    tile_data: dict (optional)
    """

    def update_tile(
        tile: dict[str, Any],
        metadata: Optional[dict[str, Any]] = None,
        annotationUID: Optional[dict[str, str]] = None,
        annotationComplete: Optional[dict[str, str]] = None,
        **kwargs: Any
    ) -> dict[str, Any]:
        if metadata is not None:
            tile["metadata"].update(metadata)
        if annotationUID is not None:
            tile["annotationUID"].update(annotationUID)
        if annotationComplete is not None:
            tile["annotationComplete"].update(annotationComplete)
        return tile

    logger.info("updating collection's content..")

    # get decoded collection content
    gallery = _decode_content(etedata["collection"].content)

    # change tile corresponding to image item with uid equal to item_uid
    for tile in gallery:
        if tile["id"] == item_uid:
            tile = update_tile({**tile}, **tile_data)

    # replace old collection's content with new one
    etedata["collection"].content = _encode_content(gallery)

    # save changes
    etedata["col_mng"].transaction(etedata["collection"])
    logger.success("updated collection's content")


def create_image_item(
    etebase: Any,
    col_uid: int,
    name: str,
    image: Union[str, Image.Image],
    metadata: dict[str, Any] = {},
    etedata: dict[str, Any] = {},
) -> Union[int, None]:
    """Create, encrypt and upload a new item to the STORE collection.

    Parameters
    ----------
    etebase
        Instance of the main etebase class.
    col_uid: int
        Collection uid.
    name: string
        Name of the new item.
    image: Union[str, Image.Image]
        Image uploaded to the new item.
    metadata: dict
        Metadata to be stored inside the new item (optional).
    etedata:
        Etebase data (i.e., collection manager, collection, item manager)
    -------
    image_uid: Union[int, None]
        New image item's uid.
    """

    logger.info("creating new image item...")

    etedata = _get_all_etedata(etebase, col_uid, etedata)

    image_data = _get_image_data(image)
    if image_data is None:
        return None

    # place the image in the expected array structure and stringify the result
    item_content = image_data["encoded_image"]

    ctime = _get_current_time()

    item_metadata = {
        "type": "gliff.image",  # STORE image item type
        "name": name,
        "createdTime": ctime,
        "modifiedTime": ctime,
        "width": image_data["width"],
        "height": image_data["height"],
    }

    col_metadata = {
        "imageName": name,
        "width": image_data["width"],
        "height": image_data["height"],
        **metadata,
    }

    # create a new item and upload it to the collection
    item = etedata["item_mng"].create(item_metadata, item_content)
    etedata["item_mng"].transaction([item])
    logger.success("created new image item, uid: {}".format(item.uid))

    # add the new tile to the collection's content
    _create_gallery_tile(
        etedata,
        item.uid,
        image_data["thumbnail"],
        col_metadata,
    )

    return item.uid


def update_image_metadata(
    etebase: Any, col_uid: int, item_uid: int, metadata: dict[str, Any], etedata: dict[str, Any] = {}
) -> None:
    """Create, encrypt and upload a new item to the STORE collection.

    Parameters
    ----------
    etebase
        Instance of the main etebase class.
    col_uid: int
        Collection uid.
    item_uid: int
        Item uid.
    metadata: dict
        New metadata to overwrite existing metadata.
    """

    logger.info("updating image item's metadata...")

    # get etebase data if missing
    etedata = _get_all_etedata(etebase, col_uid, etedata)

    # get existing item
    item = get_collection_item(etebase, col_uid, item_uid, etedata)

    # update image item's time modified (stored in the item's metadata)
    item.meta = {
        **item.meta,
        "modifiedTime": _get_current_time(),
    }

    etedata["item_mng"].transaction([item])

    # update image item metadata (stored in the collection's content)
    _update_gallery_tile(etedata, item_uid, metadata)

    logger.success("updated image item's metadata, uid: {}".format(item.uid))


def get_annotation_uid(
    etebase: Any, col_uid: int, image_item_uid: int, username: str, etedata: dict[str, Any] = {}
) -> Union[int, None]:
    """Check whether there exists an annotation for an image item with uid equal to
    image_item_uid and returns the annotation uid, otherwise returns None.

    Parameters
    ----------
    etebase
        Instance of the main etebase class.
    col_uid: int
        Collection uid.
    image_item_uid: int
        Uid for corresponding image item.
    username:
        Identifier for the user who makes the annotation.
    etedata:
        Etebase data (i.e., collection manager, collection, item manager)
    Returns
    -------
    item_uid: int or None
        Annotation item's uid.
    """
    _get_collection_and_manager(etebase, col_uid)

    gallery = _decode_content(etedata["collection"].content)

    item_uid = None
    for tile in gallery:
        if tile["id"] == image_item_uid:
            if username in tile["annotationUID"]:
                item_uid = tile["annotationUID"][username]
                break
    return item_uid


def create_annotation_item(
    etebase: Any,
    col_uid: int,
    image_item_uid: int,
    username: str,
    annotations: list[dict[str, Any]],
    metadata: dict[str, Any] = {},
    etedata: dict[str, Any] = {},
) -> int:
    """Create, encrypt and upload a new item to the STORE collection.

    Parameters
    ----------
    etebase
        Instance of the main etebase class.
    col_uid: int
        Collection uid.
    image_item_uid: int
        Uid for corresponding image item.
    name: string
        Name of the new item.
    user_id:
        Identifier for the user who makes the annotation.
    annotation: PIL.Image.Image or str
        Annotation to upload to the new item.
    metadata: dict
        Metadata to be stored inside the new item (optional).
    etedata:
        Etebase data (i.e., collection manager, collection, item manager)
    Returns
    -------
    item_uid: int
        New annotation item's uid.
    """

    logger.info("creating new annotation item...")

    etedata = _get_all_etedata(etebase, col_uid, etedata)

    # defined item's content
    item_content = _encode_content(annotations)

    # defined item's metadata
    ctime = _get_current_time()
    item_metadata = {
        "type": "gliff.annotation",
        "createdTime": ctime,
        "modifiedTime": ctime,
        "isComplete": False,
    }

    # create a new item and store it in the collection
    item = etedata["item_mng"].create(item_metadata, item_content)
    etedata["item_mng"].transaction([item])

    logger.success("created annotation item, uid: {}".format(item.uid))

    # TODO: add audit
    tile_data = {
        "metadata": metadata,
        "annotationUID": {username: item.uid},
        "annotationComplete": {username: False},
    }
    _update_gallery_tile(etedata, image_item_uid, tile_data)

    return item.uid


def update_annotation_item(
    etebase: Any,
    col_uid: int,
    image_item_uid: int,
    username: str,
    annotations: list[dict[str, Any]],
    metadata: dict[str, Any] = {},
    etedata: dict[str, Any] = {},
    annotation_item_uid: Optional[int] = None,
):
    """Create, encrypt and upload a new item to the STORE collection.

    Parameters
    ----------
    etebase
        Instance of the main etebase class.
    col_uid: int
        Collection uid.
    image_item_uid: int
        Image item's uid.
    name: string
        Name of the new item.
    username:
        Identifier for the user who makes the annotation.
    annotations: dict
        Annotation to upload to the new item.
    metadata: dict
        Metadata to be stored inside the new item (optional).
    etedata:
        Etebase data (i.e., collection manager, collection, item manager)
    annotation_item_uid: int or None
        Uid for the updated annotation (optional)
    Returns
    -------
    item_uid: int
        Annotation item's uid.
    """

    _get_all_etedata(etebase, col_uid, etedata)

    if annotation_item_uid is None:
        annotation_item_uid = get_annotation_uid(etebase, col_uid, item.uid, username, etedata)

    logger.info("updating annotation item {}...".format(annotation_item_uid))

    item = get_collection_item(etebase, col_uid, annotation_item_uid, etedata=etedata)

    # update item's metadata
    item.meta = {**item.meta, "modifiedTime": _get_current_time()}

    # remove last annotation if empty
    prev_annotations = _decode_content(item.content)
    if len(prev_annotations) > 0 & is_empty_annotation(prev_annotations[-1]):
        prev_annotations.pop()

    # update item's content
    item.content = _encode_content([*prev_annotations, *annotations])

    # save changes
    etedata["item_mng"].transaction([item])

    logger.success("updated annotation item, uid: {}".format(item.uid))

    tile_data = {
        "metadata": metadata,
    }
    _update_gallery_tile(etedata, image_item_uid, tile_data)

    return item.uid
