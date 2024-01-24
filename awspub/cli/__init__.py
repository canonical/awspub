#!/usr/bin/python3

import pathlib
import sys
import json
import logging
import argparse
from typing import Dict, Optional

from awspub.context import Context
from awspub.s3 import S3
from awspub.image import Image


logger = logging.getLogger(__name__)


def _images_filtered(context: Context, group: Optional[str]):
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


def _create(args) -> None:
    """
    Create images based on the given configuration and write json
    data to the given output
    """
    ctx = Context(args.config, args.config_mapping)
    s3 = S3(ctx)
    s3.upload_file(ctx.conf["source"]["path"], ctx.conf["source"]["architecture"])
    images: Dict[str, Dict[str, str]] = dict()
    for image_name, image in _images_filtered(ctx, args.group):
        res = image.create()
        images[image_name] = res
    args.output.write((json.dumps({"images": images}, indent=4)))


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
    logformat = "%(asctime)s:%(name)s:%(levelname)s:%(message)s"
    # log level
    loglevel = logging.INFO
    if args.log_level == "debug":
        loglevel = logging.DEBUG
    # log file
    if args.log_file:
        logging.basicConfig(filename=args.log_file, encoding="utf-8", format=logformat, level=loglevel)
    else:
        logging.basicConfig(format=logformat, level=loglevel)
    if "func" not in args:
        sys.exit(parser.print_help())
    args.func(args)
    sys.exit(0)


if __name__ == "__main__":
    main()
