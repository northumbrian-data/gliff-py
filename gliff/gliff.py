from flask import current_app
from loguru import logger
from etebase import Client, Account
import time
import json
from PIL import Image
from . import convert


def login():
    """Log in to STORE.

    Returns
    -------
    etebase
        Instance of the main etebase class.
    """

    logger.info("logging in to STORE...")
    client = Client("client-name", current_app.config["STORE_SERVER_URL"])
    etebase = Account.login(
        client,
        current_app.config["STORE_USERNAME"],
        current_app.config["STORE_PASSWORD"],
    )
    logger.success("logged in to STORE")

    accept_pending_invitations(etebase)

    return etebase


def logout(etebase):
    """Log out of STORE."""

    logger.info("logging out...")
    etebase.logout()
    logger.success("logged out")


def accept_pending_invitations(etebase):
    """Accept all pending invitations to join a STORE collection.

    Parameters
    ----------
    etebase
        Instance of the main etebase class.
    """

    invit_mng = etebase.get_invitation_manager()

    # List pending invitations
    invitations = invit_mng.list_incoming()
    logger.info("Pending Invitations")
    logger.info(invitations)
    for invitation in list(invitations.data):
        # TODO: verify that the public key is indeed the pubkey you expect

        # We can now either accept
        invit_mng.accept(invitation)
        logger.success("Invitation accepeted")


def leave_collection(etebase, col_uid):
    """Leave a collection.

    Parameters
    ----------
    etebase
        Instance of the main etebase class.
    col_uid: int
        Collection uid.
    """

    logger.info("leaving collection {}...".format(col_uid))
    col_mng, collection = _get_collection(etebase, col_uid)
    memeber_mng = col_mng.get_member_manager(collection)
    memeber_mng.leave()
    logger.info("left collection {}...".format(col_uid))


def _get_collection(etebase, col_uid):
    """Get collection manager and collection.

    Parameters
    ----------
    etebase
        Instance of the main etebase class.
    col_uid: int
        Collection uid.
    Returns
    -------
    col_mng
        Collection manager.
    collection
        STORE collection with uid equal to col_uid.
    """

    logger.info("fetching collection and manager...")
    col_mng = etebase.get_collection_manager()
    collection = col_mng.fetch(col_uid)
    logger.info("fetched collection and manager")
    return col_mng, collection


def _get_item_manager(col_mng, collection):
    """Get item manager for a given collection.

    Parameters
    ----------
    col_mng
        Collection manager.
    collection
        STORE collection.
    Returns
    -------
    item_mng
        Item manager.
    """

    logger.info("fetching item manager...")
    item_mng = col_mng.get_item_manager(collection)
    logger.info("fetched item manager")
    return item_mng


def get_image_item_content(etebase, col_uid, image_uid):
    """Retrieve the image item with uid equal to image_uid,
    from a collection with uid equal to col_uid and return
    the item's content.

    Parameters
    ----------
    etebase
        Instance of the main etebase class.
    col_uid: int
        Collection uid.
    image_uid: int
        Image uid.
    Returns
    -------
    item_mng
        Item manager.
    col_mng
        Collection manager.
    content: string
        Decoded content of image item.
    """

    try:
        col_mng, collection = _get_collection(etebase, col_uid)
        item_mng = _get_item_manager(col_mng, collection)
        logger.info("fetching image {}...".format(image_uid))
        item = item_mng.fetch(image_uid)
    except Exception as e:
        logger.error(f"Error while fetching image: {e}")
        return

    logger.info("fetched image {}".format(image_uid))
    return item_mng, col_mng, item.content.decode()


def create_collection_tile(
    col_mng, col_uid, item_uid, thumbnail, metadata=dict(), collection=None
):
    """Create, ecrypt and upload a new tile to the STORE collection.

    Parameters
    ----------
    col_mng
        Collection manager.
    col_uid: int
        Collection uid.
    item_uid: int
        Item uid.
    thumbnail: string
        Base64-encoded image's thumbnail.
    metadata: dict
        Metadata key-value pairs (optional).
    collection
        STORE collection (optional).
    """

    logger.info("updating collection's content..")
    # define new tile
    tile = {
        "id": item_uid,
        "thumbnail": thumbnail,
        "imageLabels": [],
        "metadata": metadata,
        "imageUID": item_uid,
        "annotationUID": None,
        "auditUID": None,
    }
    # get collection
    if not collection:
        collection = col_mng.fetch(col_uid)

    # get old content
    old_content = collection.content.decode()

    # add new tile
    content = json.loads(old_content)
    content.append(tile)
    content = json.dumps(content, separators=(",", ":"))

    # replace old content
    collection.content = content.encode()

    # save changes to the collection
    col_mng.transaction(collection)
    logger.success("updated collection's content")


def create_image_item(col_mng, col_uid, name, image, item_mng=None, metadata={}):
    """Create, encrypt and upload a new item to the STORE collection.

    Parameters
    ----------
    col_mng
        Collection manager.
    col_uid: int
        Collection uid.
    name: string
        Name of the new item.
    image: PIL.Image.Image or str
        Image uploaded to the new item.
    item_mng
        Item manager (optional).
    metadata
        Metadata to be stored inside the new item (optional).
    Returns
    -------
    image_uid: int
        New image item's uid.
    """

    logger.info("creating and uploading a new image item...")

    # checks on type of image param
    if type(image) == Image.Image:
        image_pil = image
        image = convert.pil_to_base64_image(image)
    elif isinstance(image, str):
        image_pil = convert.base64_to_pil_image(image)
    else:
        logger.error("image should be of type PIL.Image.Image or str")
        return

    # get collection
    collection = col_mng.fetch(col_uid)

    # get item manager
    if not item_mng:
        item_mng = _get_item_manager(col_mng, collection)

    # create new item
    ctime = int(round(time.time() * 1000))

    # get image width and height
    width, height = image_pil.size

    # place the image in the expected array structure and stringify the result
    item_content = json.dumps([[image]], separators=(",", ":")).encode()

    item_metadata = {
        "type": "gliff.image",  # STORE image item type
        "name": name,
        "createdTime": ctime,
        "modifiedTime": ctime,
        "width": width,
        "height": height,
    }

    # make thumbnail
    thumbnail = convert.get_thumbnail_from_pil_image(image_pil)

    # make collection metadata
    col_metadata = {
        "imageName": name,
        "width": width,
        "height": height,
        **metadata,
    }

    # create a new item and upload it to the collection
    item = item_mng.create(item_metadata, item_content)
    item_mng.batch([item])
    logger.success("uploaded new image item, uid: {}".format(item.uid))

    # add a new tile to the collection's content
    create_collection_tile(
        col_mng, col_uid, item.uid, thumbnail, col_metadata, collection
    )
    return item.uid
