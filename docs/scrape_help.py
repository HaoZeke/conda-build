#!/usr/bin/env python
# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
import json
import re
import sys
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from os import makedirs, pathsep
from os.path import abspath, dirname, isdir, join
from shlex import quote
from subprocess import PIPE, STDOUT, Popen, check_output

manpath = join(dirname(__file__), "build", "man")
if not isdir(manpath):
    makedirs(manpath)
rstpath = join(dirname(__file__), "source", "commands")
if not isdir(rstpath):
    makedirs(rstpath)

RST_HEADER = """
.. _{command}_ref:

conda {command}
=======================

.. raw:: html

"""


def run_command(*args, **kwargs):
    include_stderr = kwargs.pop("include_stderr", False)
    stderr_pipe = STDOUT if include_stderr else PIPE
    p = Popen(*args, stdout=PIPE, stderr=stderr_pipe, **kwargs)
    out, err = p.communicate()
    if err is None:
        err = b""
    out, err = out.decode("utf-8"), err.decode("utf-8")
    if p.returncode != 0:
        print(
            "{!r} failed with error code {}".format(
                " ".join(map(quote, args[0])), p.returncode
            ),
            file=sys.stderr,
        )
    elif err:
        print("{!r} gave stderr output: {}".format(" ".join(*args), err))

    return out


def str_check_output(*args, **kwargs):
    return check_output(*args, **kwargs).decode("utf-8")


def conda_help(cache=[]):
    if cache:
        return cache[0]
    cache.append(str_check_output(["conda", "--help"]))
    return cache[0]


def conda_command_help(command):
    return str_check_output(["conda"] + command.split() + ["--help"])


def conda_commands():
    print("Getting list of core commands")
    help = conda_help()
    commands = []
    start = False
    for line in help.splitlines():
        # Commands start after "command" header
        if line.strip() == "command":
            start = True
            continue
        if start:
            # The end of the commands
            if not line:
                break
            if line[4] != " ":
                commands.append(line.split()[0])
    return commands


def external_commands():
    print("Getting list of external commands")
    help = conda_help()
    commands = []
    start = False
    for line in help.splitlines():
        # Commands start after "command" header
        if line.strip() == "other commands:":
            start = True
            continue
        if start:
            # The end of the commands
            if not line:
                break
            if line[4] != " ":
                commands.append(line.split()[0])

    # TODO: Parallelize this
    print("Getting list of external subcommands")
    subcommands_re = re.compile(r"\s*\{(.*)\}\s*")
    # Check for subcommands (like conda skeleton pypi)
    command_help = {}

    def get_help(command):
        command_help[command] = conda_command_help(command)
        print(f"Checked for subcommand help for {command}")

    with ThreadPoolExecutor(len(commands)) as executor:
        # list() is needed for force exceptions to be raised
        list(executor.map(get_help, commands))

    for command in command_help:
        help = command_help[command]
        start = False
        for line in help.splitlines():
            if line.strip() == "positional arguments:":
                start = True
                continue
            if start:
                m = subcommands_re.match(line)
                if m:
                    commands.extend([f"{command} {i}" for i in m[1].split(",")])
                break
    return commands


def man_replacements():
    # XXX: We should use conda-api for this, but it's currently annoying to set the
    # root prefix with.
    info = json.loads(str_check_output(["conda", "info", "--json"]))
    return OrderedDict(
        [
            (info["default_prefix"], "default prefix"),
            (pathsep.join(info["envs_dirs"]), "envs dirs"),
            # For whatever reason help2man won't italicize these on its own
            # Note these require conda > 3.7.1
            (info["user_rc_path"], r"\fI\,user .condarc path\/\fP"),
            (info["sys_rc_path"], r"\fI\,system .condarc path\/\fP"),
            (info["root_prefix"], r"root prefix"),
        ]
    )


def generate_man(command):
    conda_version = run_command(["conda", "--version"], include_stderr=True)

    manpage = ""
    retries = 5
    while not manpage and retries:
        manpage = run_command(
            [
                "help2man",
                "--name",
                f"conda {command}",
                "--section",
                "1",
                "--source",
                "Anaconda, Inc.",
                "--version-string",
                conda_version,
                "--no-info",
                f"conda {command}",
            ]
        )
        retries -= 1

    if not manpage:
        sys.exit(f"Error: Could not get help for conda {command}")

    replacements = man_replacements()
    for text in replacements:
        manpage = manpage.replace(text, replacements[text])
    with open(join(manpath, f'conda-{command.replace(" ", "-")}.1'), "w") as f:
        f.write(manpage)

    print(f"Generated manpage for conda {command}")


def generate_html(command):
    command_file = command.replace(" ", "-")

    # Use abspath so that it always has a path separator
    man = Popen(
        ["man", abspath(join(manpath, f"conda-{command_file}.1"))], stdout=PIPE
    )
    htmlpage = check_output(
        [
            "man2html",
            "-bare",
            "title",
            f"conda-{command_file}",
            "-topm",
            "0",
            "-botm",
            "0",
        ],
        stdin=man.stdout,
    )

    with open(join(manpath, f"conda-{command_file}.html"), "wb") as f:
        f.write(htmlpage)
    print(f"Generated html for conda {command}")


def write_rst(command, sep=None):
    command_file = command.replace(" ", "-")
    with open(join(manpath, f"conda-{command_file}.html")) as f:
        html = f.read()

    rp = rstpath
    if sep:
        rp = join(rp, sep)
    if not isdir(rp):
        makedirs(rp)
    with open(join(rp, f"conda-{command_file}.rst"), "w") as f:
        f.write(RST_HEADER.format(command=command))
        for line in html.splitlines():
            f.write("   ")
            f.write(line)
            f.write("\n")
    print(f"Generated rst for conda {command}")


def main():
    core_commands = []

    # let's just hard-code this for now
    # build_commands = ()
    build_commands = [
        "build",
        "convert",
        "develop",
        "index",
        "inspect",
        "inspect channels",
        "inspect linkages",
        "inspect objects",
        "metapackage",
        "render",
        "skeleton",
        "skeleton cpan",
        "skeleton cran",
        "skeleton luarocks",
        "skeleton pypi",
    ]

    commands = sys.argv[1:] or core_commands + build_commands

    def gen_command(command):
        generate_man(command)
        generate_html(command)

    with ThreadPoolExecutor(10) as executor:
        # list() is needed to force exceptions to be raised
        list(executor.map(gen_command, commands))

    for command in [c for c in build_commands if c in commands]:
        write_rst(command)


if __name__ == "__main__":
    sys.exit(main())
