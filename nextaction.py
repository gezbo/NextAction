#!/usr/bin/env python

import logging
import argparse

# noinspection PyPackageRequirements
from todoist.api import TodoistAPI

import time
import sys
from datetime import datetime


def get_subitems(items, parent_item=None):
    """Search a flat item list for child items"""
    result_items = []
    found = False
    if parent_item:
        required_indent = parent_item['indent'] + 1
    else:
        required_indent = 1
    for item in items:
        if parent_item:
            if not found and item['id'] != parent_item['id']:
                continue
            else:
                found = True
            if item['indent'] == parent_item['indent'] and item['id'] != parent_item['id']:
                return result_items
        elif item['indent'] == required_indent:
            result_items.append(item)
    return result_items


def main():

    parser = argparse.ArgumentParser()
    parser.add_argument('-a', '--api_key', help='Todoist API Key')
    parser.add_argument('-l', '--label', help='The next action label to use', default='next_action')
    parser.add_argument('-d', '--delay', help='Specify the delay in seconds between syncs', default=5, type=int)
    parser.add_argument('--debug', help='Enable debugging', action='store_true')
    parser.add_argument('--inbox', help='The method the Inbox project should be processed',
                        default='parallel', choices=['parallel', 'serial'])
    parser.add_argument('--parallel_suffix', default='=')
    parser.add_argument('--serial_suffix', default='-')
    parser.add_argument('--hide_future', help='Hide future dated next actions until the specified number of days',
                        default=7, type=int)
    args = parser.parse_args()

    # Set debug
    if args.debug:
        log_level = logging.DEBUG
    else:
        log_level = logging.INFO
    logging.basicConfig(level=log_level)

    # Check we have a API key
    if not args.api_key:
        logging.error('No API key set, exiting...')
        sys.exit(1)

    # Run the initial sync
    logging.debug('Connecting to the Todoist API')
    api = TodoistAPI(token=args.api_key)
    logging.debug('Syncing the current state from the API')
    api.sync(resource_types=['projects', 'labels', 'items'])

    # Check the next action label exists
    labels = api.labels.all(lambda x: x['name'] == args.label)
    if len(labels) > 0:
        label_id = labels[0]['id']
        logging.debug('Label %s found as label id %d', args.label, label_id)
    else:
        logging.error("Label %s doesn't exist, please create it or change TODOIST_NEXT_ACTION_LABEL.", args.label)
        sys.exit(1)

    def get_project_type(project_object):
        """Identifies how a project should be handled"""
        name = project_object['name'].strip()
        if project['name'] == 'Inbox':
            return args.inbox
        elif name[-1] == args.parallel_suffix:
            return 'parallel'
        elif name[-1] == args.serial_suffix:
            return 'serial'

    # Main loop
    while True:
        try:
            api.sync(resource_types=['projects', 'labels', 'items'])
        except Exception as e:
            logging.exception('Error trying to sync with Todoist API: %s' % str(e))
        else:
            for project in api.projects.all():
                project_type = get_project_type(project)
                if project_type:
                    logging.debug('Project %s being processed as %s', project['name'], project_type)

                    items = sorted(api.items.all(lambda x: x['project_id'] == project['id']), key=lambda x: x['item_order'])

                    for item in items:
                        labels = item['labels']

                        # If its too far in the future, remove the next_action tag and skip
                        if args.hide_future > 0 and 'due_date_utc' in item.data and item['due_date_utc'] is not None:
                            due_date = datetime.strptime(item['due_date_utc'], '%a %d %b %Y %H:%M:%S +0000')
                            future_diff = (due_date - datetime.utcnow()).total_seconds()
                            if future_diff >= (args.hide_future * 86400):
                                if label_id in labels:
                                    labels.remove(label_id)
                                    logging.debug('Updating %s without label as its too far in the future', item['content'])
                                    item.update(labels=labels)
                                continue

                        # Process item
                        if project_type == 'serial':
                            if item['item_order'] == 1:
                                if label_id not in labels:
                                    labels.append(label_id)
                                    logging.debug('Updating %s with label', item['content'])
                                    item.update(labels=labels)
                            else:
                                if label_id in labels:
                                    labels.remove(label_id)
                                    logging.debug('Updating %s without label', item['content'])
                                    item.update(labels=labels)
                        elif project_type == 'parallel':
                            if label_id not in labels:
                                logging.debug('Updating %s with label', item['content'])
                                labels.append(label_id)
                                item.update(labels=labels)

            api.commit()
        logging.debug('Sleeping for %d seconds', args.delay)
        time.sleep(args.delay)


if __name__ == '__main__':
    main()
