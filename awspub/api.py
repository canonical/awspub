import logging
import pathlib
from typing import Dict, Iterator, List, Optional, Tuple

from awspub.context import Context
from awspub.image import Image, _ImageInfo
from awspub.s3 import S3

logger = logging.getLogger(__name__)


def _images_grouped(
    images: List[Tuple[str, Image, Dict[str, _ImageInfo]]], group: Optional[str]
) -> Tuple[Dict[str, Dict[str, str]], Dict[str, Dict[str, Dict[str, str]]]]:
    """
    Group the given images by name and by group

    :param images: the images
    :type images: List[Tuple[str, Image, Dict[str, _ImageInfo]]]
    :param group: a optional group name
    :type group: Optional[str]
    :return: the images grouped by name and by group
    :rtype: Tuple[Dict[str, Dict[str, str]], Dict[str, Dict[str, Dict[str, str]]]
    """
    images_by_name: Dict[str, Dict[str, str]] = dict()
    images_by_group: Dict[str, Dict[str, Dict[str, str]]] = dict()
    for image_name, image, image_result in images:
        images_region_id: Dict[str, str] = {key: val.image_id for (key, val) in image_result.items()}
        images_by_name[image_name] = images_region_id
        for image_group in image.conf.get("groups", []):
            if group and image_group != group:
                continue
            if not images_by_group.get(image_group):
                images_by_group[image_group] = {}
            images_by_group[image_group][image_name] = images_region_id
    return images_by_name, images_by_group


def _images_filtered(context: Context, group: Optional[str]) -> Iterator[Tuple[str, Image]]:
    """
    Filter the images from ctx based on the given args

    :param context: the context
    :type context: a awspub.context.Context instance
    :param group: a optional group name
    :type group: Optional[str]
    """
    for image_name in context.conf["images"].keys():
        image = Image(context, image_name)
        if group:
            # limit the images to process to the group given on the command line
            if group not in image.conf.get("groups", []):
                logger.info(f"skipping image {image_name} because not part of group {group}")
                continue

        logger.info(f"processing image {image_name} (group: {group})")
        yield image_name, image


def create(
    config: pathlib.Path, config_mapping: pathlib.Path, group: Optional[str]
) -> Tuple[Dict[str, Dict[str, str]], Dict[str, Dict[str, Dict[str, str]]]]:
    """
    Create images in the partition of the used account based on
    the given configuration file and the config mapping

    :param config: the configuration file path
    :type config: pathlib.Path
    :param config_mapping: the config template mapping file path
    :type config_mapping: pathlib.Path
    :param group: only handles images from given group
    :type group: Optional[str]
    :return: the images grouped by name and by group
    :rtype: Tuple[Dict[str, Dict[str, str]], Dict[str, Dict[str, Dict[str, str]]]
    """

    ctx = Context(config, config_mapping)
    s3 = S3(ctx)
    s3.upload_file(ctx.conf["source"]["path"])
    images: List[Tuple[str, Image, Dict[str, _ImageInfo]]] = []
    for image_name, image in _images_filtered(ctx, group):
        image_result: Dict[str, _ImageInfo] = image.create()
        images.append((image_name, image, image_result))
    images_by_name, images_by_group = _images_grouped(images, group)
    return images_by_name, images_by_group


def list(
    config: pathlib.Path, config_mapping: pathlib.Path, group: Optional[str]
) -> Tuple[Dict[str, Dict[str, str]], Dict[str, Dict[str, Dict[str, str]]]]:
    """
    List images in the partition of the used account based on
    the given configuration file and the config mapping

    :param config: the configuration file path
    :type config: pathlib.Path
    :param config_mapping: the config template mapping file path
    :type config_mapping: pathlib.Path
    :param group: only handles images from given group
    :type group: Optional[str]
    :return: the images grouped by name and by group
    :rtype: Tuple[Dict[str, Dict[str, str]], Dict[str, Dict[str, Dict[str, str]]]
    """
    ctx = Context(config, config_mapping)
    images: List[Tuple[str, Image, Dict[str, _ImageInfo]]] = []
    for image_name, image in _images_filtered(ctx, group):
        image_result: Dict[str, _ImageInfo] = image.list()
        images.append((image_name, image, image_result))

    images_by_name, images_by_group = _images_grouped(images, group)
    return images_by_name, images_by_group


def publish(config: pathlib.Path, config_mapping: pathlib.Path, group: Optional[str]):
    """
    Make available images in the partition of the used account based on
    the given configuration file public

    :param config: the configuration file path
    :type config: pathlib.Path
    :param config_mapping: the config template mapping file path
    :type config_mapping: pathlib.Path
    :param group: only handles images from given group
    :type group: Optional[str]
    """
    ctx = Context(config, config_mapping)
    for image_name, image in _images_filtered(ctx, group):
        image.publish()


def cleanup(config: pathlib.Path, config_mapping: pathlib.Path, group: Optional[str]):
    """
    Cleanup available images in the partition of the used account based on
    the given configuration file

    :param config: the configuration file path
    :type config: pathlib.Path
    :param config_mapping: the config template mapping file path
    :type config_mapping: pathlib.Path
    :param group: only handles images from given group
    :type group: Optional[str]
    """
    ctx = Context(config, config_mapping)
    for image_name, image in _images_filtered(ctx, group):
        image.cleanup()
