#!/usr/bin/python3

import argparse
import json
import logging
import pathlib
import sys

import awspub

logger = logging.getLogger(__name__)


def _create(args) -> None:
    """
    Create images based on the given configuration and write json
    data to the given output
    """
    images_by_name, images_by_group = awspub.create(args.config, args.config_mapping, args.group)
    images_json = json.dumps({"images": images_by_name, "images-by-group": images_by_group}, indent=4)
    args.output.write(images_json)


def _list(args) -> None:
    """
    List images based on the given configuration and write json
    data to the given output
    """
    images_by_name, images_by_group = awspub.list(args.config, args.config_mapping, args.group)
    images_json = json.dumps({"images": images_by_name, "images-by-group": images_by_group}, indent=4)
    args.output.write(images_json)


def _verify(args) -> None:
    """
    Verify available images against configuration
    """
    problems = awspub.verify(args.config, args.config_mapping, args.group)
    args.output.write((json.dumps({"problems": problems}, indent=4)))


def _cleanup(args) -> None:
    """
    Cleanup available images
    """
    awspub.cleanup(args.config, args.config_mapping, args.group)


def _public(args) -> None:
    """
    Make available images public
    """
    awspub.public(args.config, args.config_mapping, args.group)


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
