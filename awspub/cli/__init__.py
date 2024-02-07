#!/usr/bin/python3

import pathlib
import sys
import json
import logging
import argparse
from typing import Dict, Optional, List, Tuple, Iterator

from awspub.context import Context
from awspub.s3 import S3
from awspub.image import Image


logger = logging.getLogger(__name__)


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

        logger.info(f"processing image {image_name} from group {group}")
        yield image_name, image


def _images_json(images: List[Tuple[str, Image, Dict[str, Optional[str]]]], group: Optional[str]):
    """
    Return json data which is the output for eg. the create and list commands
    That data has images listed by name but also images grouped by the group
    """
    images_by_name: Dict[str, Dict[str, Optional[str]]] = dict()
    images_by_group: Dict[str, Dict[str, Dict[str, Optional[str]]]] = dict()
    for image_name, image, result in images:
        images_by_name[image_name] = result
        for image_group in image.conf.get("groups", []):
            if group and image_group != group:
                continue
            if not images_by_group.get(image_group):
                images_by_group[image_group] = {}
            images_by_group[image_group][image_name] = result
    return json.dumps({"images": images_by_name, "images-by-group": images_by_group}, indent=4)


def _create(args) -> None:
    """
    Create images based on the given configuration and write json
    data to the given output
    """
    ctx = Context(args.config, args.config_mapping)
    s3 = S3(ctx)
    s3.upload_file(ctx.conf["source"]["path"], ctx.conf["source"]["architecture"])
    images = []
    for image_name, image in _images_filtered(ctx, args.group):
        res = image.create()
        images.append((image_name, image, res))

    args.output.write((_images_json(images, args.group)))


def _list(args) -> None:
    """
    List images based on the given configuration and write json
    data to the given output
    """
    ctx = Context(args.config, args.config_mapping)
    images = []
    for image_name, image in _images_filtered(ctx, args.group):
        res = image.list()
        images.append((image_name, image, res))

    args.output.write((_images_json(images, args.group)))


def _verify(args) -> None:
    """
    Verify available images against configuration
    """
    problems: Dict[str, Dict] = dict()
    ctx = Context(args.config, args.config_mapping)
    for image_name, image in _images_filtered(ctx, args.group):
        problems[image_name] = image.verify()
    args.output.write((json.dumps({"problems": problems}, indent=4)))


def _cleanup(args) -> None:
    """
    Cleanup available images
    """
    ctx = Context(args.config, args.config_mapping)
    for image_name, image in _images_filtered(ctx, args.group):
        image.cleanup()


def _public(args) -> None:
    """
    Make available images public
    """
    ctx = Context(args.config, args.config_mapping)
    for image_name, image in _images_filtered(ctx, args.group):
        image.public()


def _parser():
    parser = argparse.ArgumentParser(description="AWS EC2 publication tool")
    parser.add_argument("--log-level", choices=["info", "debug"], default="info")
    parser.add_argument("--log-file", type=pathlib.Path, help="write log to given file instead of stdout")
    parser.add_argument("--log-console", action=argparse.BooleanOptionalAction, help="write log to stdout")
    p_sub = parser.add_subparsers(help="sub-command help")

    # create
    p_create = p_sub.add_parser("create", help="Create images")
    p_create.add_argument(
        "--output", type=argparse.FileType("w+"), help="output file path. defaults to stdout", default=sys.stdout
    )
    p_create.add_argument("--config-mapping", type=pathlib.Path, help="the image config template mapping file path")
    p_create.add_argument("--group", type=str, help="only handles images from given group")
    p_create.add_argument("config", type=pathlib.Path, help="the image configuration file path")
    p_create.set_defaults(func=_create)

    # list
    p_list = p_sub.add_parser("list", help="List images (but don't modify anything)")
    p_list.add_argument(
        "--output", type=argparse.FileType("w+"), help="output file path. defaults to stdout", default=sys.stdout
    )
    p_list.add_argument("--config-mapping", type=pathlib.Path, help="the image config template mapping file path")
    p_list.add_argument("--group", type=str, help="only handles images from given group")
    p_list.add_argument("config", type=pathlib.Path, help="the image configuration file path")
    p_list.set_defaults(func=_list)

    # verify
    p_verify = p_sub.add_parser("verify", help="Verify images")
    p_verify.add_argument(
        "--output", type=argparse.FileType("w+"), help="output file path. defaults to stdout", default=sys.stdout
    )
    p_verify.add_argument("--config-mapping", type=pathlib.Path, help="the image config template mapping file path")
    p_verify.add_argument("--group", type=str, help="only handles images from given group")
    p_verify.add_argument("config", type=pathlib.Path, help="the image configuration file path")

    p_verify.set_defaults(func=_verify)

    # cleanup
    p_cleanup = p_sub.add_parser("cleanup", help="Cleanup images")
    p_cleanup.add_argument(
        "--output", type=argparse.FileType("w+"), help="output file path. defaults to stdout", default=sys.stdout
    )
    p_cleanup.add_argument("--config-mapping", type=pathlib.Path, help="the image config template mapping file path")
    p_cleanup.add_argument("--group", type=str, help="only handles images from given group")
    p_cleanup.add_argument("config", type=pathlib.Path, help="the image configuration file path")

    p_cleanup.set_defaults(func=_cleanup)

    # public
    p_public = p_sub.add_parser("public", help="Publish images")
    p_public.add_argument(
        "--output", type=argparse.FileType("w+"), help="output file path. defaults to stdout", default=sys.stdout
    )
    p_public.add_argument("--config-mapping", type=pathlib.Path, help="the image config template mapping file path")
    p_public.add_argument("--group", type=str, help="only handles images from given group")
    p_public.add_argument("config", type=pathlib.Path, help="the image configuration file path")

    p_public.set_defaults(func=_public)

    return parser


def main():
    parser = _parser()
    args = parser.parse_args()
    log_formatter = logging.Formatter("%(asctime)s:%(name)s:%(levelname)s:%(message)s")
    # log level
    loglevel = logging.INFO
    if args.log_level == "debug":
        loglevel = logging.DEBUG
    root_logger = logging.getLogger()
    root_logger.setLevel(loglevel)
    # log file
    if args.log_file:
        file_handler = logging.FileHandler(filename=args.log_file)
        file_handler.setFormatter(log_formatter)
        root_logger.addHandler(file_handler)
    # log console
    if args.log_console:
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(log_formatter)
        root_logger.addHandler(console_handler)
    if "func" not in args:
        sys.exit(parser.print_help())
    args.func(args)
    sys.exit(0)


if __name__ == "__main__":
    main()
