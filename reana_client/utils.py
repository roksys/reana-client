# -*- coding: utf-8 -*-
#
# This file is part of REANA.
# Copyright (C) 2017, 2018 CERN.
#
# REANA is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.
"""REANA client utils."""

import json
import logging
import os
import sys
from uuid import UUID

import click
import yadageschemas
import yaml
from cwltool.main import main
from jsonschema import ValidationError, validate
from reana_commons.serial import serial_load
from six import StringIO

from reana_client.config import reana_yaml_schema_file_path


def workflow_uuid_or_name(ctx, param, value):
    """Get UUID of workflow from configuration / cache file based on name."""
    if not value:
        click.echo(click.style(
            'Workflow name must be provided either with '
            '`--workflow` option or with REANA_WORKON '
            'environment variable', fg='red'),
            err=True)
    else:
        return value


def yadage_load(workflow_file, toplevel='.'):
    """Validate and return yadage workflow specification.

    :param workflow_file: A specification file compliant with
        `yadage` workflow specification.
    :returns: A dictionary which represents the valid `yadage` workflow.
    """
    return yadageschemas.load(workflow_file, toplevel=toplevel,
                              schema_name='yadage/workflow-schema',
                              schemadir=None, validate=True)


def cwl_load(workflow_file):
    """Validate and return cwl workflow specification.

    :param workflow_file: A specification file compliant with
        `cwl` workflow specification.
    :returns: A dictionary which represents the valid `cwl` workflow.
    """
    mystdout = StringIO()
    main(["--pack", "--quiet", workflow_file], stdout=mystdout)
    value = mystdout.getvalue()
    return json.loads(value)


workflow_load = {
    'yadage': yadage_load,
    'cwl': cwl_load,
    'serial': serial_load,
}
"""Dictionary to extend with new workflow specification loaders."""


def load_workflow_spec(workflow_type, workflow_file, **kwargs):
    """Validate and return machine readable workflow specifications.

    :param workflow_type: A supported workflow specification type.
    :param workflow_file: A workflow file compliant with `workflow_type`
        specification.
    :returns: A dictionary which represents the valid workflow specification.
    """
    return workflow_load[workflow_type](workflow_file, **kwargs)


def load_reana_spec(filepath, skip_validation=False):
    """Load and validate reana specification file.

    :raises IOError: Error while reading REANA spec file from given filepath`.
    :raises ValidationError: Given REANA spec file does not validate against
        REANA specification.
    """
    try:
        with open(filepath) as f:
            reana_yaml = yaml.load(f.read())

        if not (skip_validation):
            logging.info('Validating REANA specification file: {filepath}'
                         .format(filepath=filepath))
            _validate_reana_yaml(reana_yaml)

        kwargs = {}
        if reana_yaml['workflow']['type'] == 'serial':
            kwargs['specification'] = reana_yaml['workflow'].\
                get('specification')
            kwargs['parameters'] = \
                reana_yaml.get('inputs', {}).get('parameters', {})

        reana_yaml['workflow']['specification'] = load_workflow_spec(
            reana_yaml['workflow']['type'],
            reana_yaml['workflow'].get('file'),
            **kwargs
        )

        if reana_yaml['workflow']['type'] == 'cwl' and \
                'inputs' in reana_yaml:
            with open(reana_yaml['inputs']['parameters']['input']) as f:
                reana_yaml['inputs']['parameters']['input'] = yaml.load(f)

        return reana_yaml
    except IOError as e:
        logging.info(
            'Something went wrong when reading specifications file from '
            '{filepath} : \n'
            '{error}'.format(filepath=filepath, error=e.strerror))
        raise e
    except Exception as e:
        raise e


def _validate_reana_yaml(reana_yaml):
    """Validate REANA specification file according to jsonschema.

    :param reana_yaml: Dictionary which represents REANA specifications file.
    :raises ValidationError: Given REANA spec file does not validate against
        REANA specification schema.
    """
    try:
        with open(reana_yaml_schema_file_path, 'r') as f:
            reana_yaml_schema = json.loads(f.read())

            validate(reana_yaml, reana_yaml_schema)

    except IOError as e:
        logging.info(
            'Something went wrong when reading REANA validation schema from '
            '{filepath} : \n'
            '{error}'.format(filepath=reana_yaml_schema_file_path,
                             error=e.strerror))
        raise e
    except ValidationError as e:
        logging.info('Invalid REANA specification: {error}'
                     .format(error=e.message))
        raise e


def is_uuid_v4(uuid_or_name):
    """Check if given string is a valid UUIDv4."""
    # Based on https://gist.github.com/ShawnMilo/7777304
    try:
        uuid = UUID(uuid_or_name, version=4)
    except Exception:
        return False

    return uuid.hex == uuid_or_name.replace('-', '')


def get_workflow_name_and_run_number(workflow_name):
    """Return name and run_number of a workflow.

    :param workflow_name: String representing Workflow name.

        Name might be in format 'reana.workflow.123' with arbitrary
        number of dot-delimited substrings, where last substring specifies
        the run number of the workflow this workflow name refers to.

        If name does not contain a valid run number, name without run number
        is returned.
    """
    # Try to split a dot-separated string.
    try:
        name, run_number = workflow_name.rsplit('.', 1)

        if not run_number.isdigit():
            # `workflow_name` was split, so it is a dot-separated string
            # but it didn't contain a valid `run_number`.
            # Assume that this dot-separated string is the name of
            # the workflow and return just this without a `run_number`.
            return workflow_name, ''

        return name, run_number

    except ValueError:
        # Couldn't split. Probably not a dot-separated string.
        # Return the name given as parameter without a `run_number`.
        return workflow_name, ''


def get_workflow_root():
    """Return the current workflow root directory."""
    reana_yaml = 'reana.yaml'
    workflow_root = os.getcwd()

    while True:
        file_list = os.listdir(workflow_root)
        parent_dir = os.path.dirname(workflow_root)
        if reana_yaml in file_list:
            break
        else:
            if workflow_root == parent_dir:
                click.echo(click.style(
                    'Not an workflow directory (or any of the parent'
                    ' directories).\nPlease upload from inside'
                    ' the directory containing the reana.yaml '
                    'file of your workflow.', fg='red'))
                sys.exit(1)
            else:
                workflow_root = parent_dir
    workflow_root += '/'
    return workflow_root
