# GDX Analytics Snowplow Gateway Service
[![Lifecycle:Dormant](https://img.shields.io/badge/Lifecycle-Dormant-ff7f2a)]
---
A gateway service to the Snowplow analytics service for BCGov OpenShift projects

## Notes

This repo is being archived as it is currently not in use. Please see ticket https://apps.itsm.gov.bc.ca/jira/browse/GDXDSD-5242 for more information.


## Features

The GDX Analytics Snowplow Gateway Service written in Python and running on Pipenv hosted as a containerized service to provide an on-cluster endpoint for projects thats run on the Government of British Columbia's OpenShift container platform. This provides an alternative to post analytics events to, in order to avoid client projects from making off-cluster connections to the AWS hosted Snowplow endpoint. This project handles the analytics transfer to AWS, features 7 day backups of all posted data, and provides auditing capability on those.

## Usage

The CI/CD pipeline for this project is a Jenkins instance running from the Tools namespace. The Jenkins pipeline is hooked to this repository and is triggered to build and deploy to the Dev namespace when a PR to master is created. From there, the pipeline is can be push-button deployed to the Test and Production namespaces. Deploying to production will trigger a cleanup stage to merge the PR and clean up the Dev and Test namespaces.

Posted JSON files must be correctly parsable as an event. An example is provided below.

### Parsable POST JSON Example

The following snippet of JSON is an example of a POST body which will validate against the [`post_schema.json`](./app/post_schema.json).

```json
{
    "env": "test",
    "namespace": "CAPS_test",
    "app_id": "CAPS_test",
    "dvce_created_tstamp": 1555802400000,
    "event_data_json": {
        "contexts": [
            {
                "data": {
                    "client_id": 283732,
                    "service_count": 2,
                    "quick_txn": false
                },
                "schema": "iglu:ca.bc.gov.cfmspoc/citizen/jsonschema/3-0-0"
            },
            {
                "data": {
                    "office_type": "reception",
                    "office_id": 14
                },
                "schema": "iglu:ca.bc.gov.cfmspoc/office/jsonschema/1-0-0"
            },
            {
                "data": {
                    "agent_id": 22,
                    "role": "CSR",
                    "quick_txn": false
                },
                "schema": "iglu:ca.bc.gov.cfmspoc/agent/jsonschema/2-0-0"
            }
        ],
        "data": {
            "inaccurate_time": false,
            "quantity": 2
        },
        "schema": "iglu:ca.bc.gov.cfmspoc/finish/jsonschema/2-0-0"
    }
}
```

## Development

##### Install and Launch

For local deployment and testing purposes:

1. clone this repostitory and cd to the [/app](./app/) directory
2. pipenv install
3. pipenv run python app.py
4. post test JSON events to the localhost running instance of the server

## Deploying

The regular approach is to create Pull Requests onto the master branch of this repository, but the following steps can be used to build locally and deploy manually to an Openshift namespace.

### To Build Locally, and Deploy to OpenShift
This circumvents the Jenkins CI/CD pipeline in the **`TOOLS`** project on OpenShift. It is an alternative to the rsync/hot-deploy method described in the section below (and which is not yet an option).

#### Build
```
cd .pipeline
# Building
npm run build -- --pr=0 --dev-mode=true

```
#### Deploy
```
# Deploy to DEV
cd .pipeline
npm run deploy -- --pr=0 --env=dev
```
#### Clean
```
cd .pipeline

# Build environment
npm run clean -- --pr=0 --env=build

# DEV environment
npm run clean -- --pr=0 --env=dev

```

### Sync Working Directory to Pod

Currently we have no way to [hot-deploy](https://docs.openshift.com/container-platform/3.11/using_images/s2i_images/python.html#python-hot-deploy) the app.py. The following steps are not recommended until hot deploy is set up, since while the contents of the [app.py](./app/app.py) can be updated on a given pod; it will not reload the Python process running that script from the one that is already loaded in memory.

You will need to set the autoscale to one pod to avoid the route sometimes calling a pod you aren't `rsync`ing to. In **`DEV`**, in the Application > Deployments > Actions > Edit Autoscaler section, set Min pods from 2 to 1, then save. The HPA will autoscale your pods down to one.

Locally, run:

```bash
cd "$(git rev-parse --show-toplevel)/app" # navigate to your working directory (./app)
oc rsync --no-perms=true ./ <pod_id>:/opt/app-root/src
oc rsh <pod_id>
cat /opt/app-root/src/app.py
```

### Postgres Schema Setup

#### Local Development

Configure your Postgres environment to include the role and schema necessary (see the commented lines in [./schema/caps_schema.sql](./schema/caps_schema.sql)). Build the tables and give the application user (`caps` is the example) ownership. Set the environment variables required for [./app/app.py](./app/app.py); `DB_HOSTNAME`, `DB_NAME`, `DB_USERNAME`, and `DB_PASSWORD` to access Postgres.

#### OpenShift Development

The DevOps recommendation is to port-forward to the local development workstation, run the PostgreSQL database locally, and connect remotely to that from an OpenShift Python pod from which you will be `rsync`ing (see above) your working directory (most likely [./app](./app)).

on *each* postgres pod in Dev, connect to the caps DB and create the schema, then create the tables

```bash
cd "$(git rev-parse --show-toplevel)/schema"
oc rsync --no-perms=true ./ <pod_id>:/home/postgres
oc rsh <pod_id>
psql caps -f caps_schema.sql
```

## Project Status
 
This project is in production and the GDX Analytics Team will continue to update and maintain the project as required.
 
## Related Repositories
 
### [GDX-Analytics/](https://github.com/bcgov/GDX-Analytics)
 
This is the central repository for work by the GDX Analytics Team.
 
## Getting Help or Reporting an Issue
 
For any questions regarding this project, or for inquiries about starting a new analytics account, please contact the GDX Analytics Team.

## How to Contribute

If you would like to contribute, please see our [CONTRIBUTING](CONTRIBUTING.md) guideleines.

Please note that this project is released with a [Contributor Code of Conduct](CODE_OF_CONDUCT.md). By participating in this project you agree to abide by its terms.

## License
```
Copyright 2015 Province of British Columbia
 
Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at
 
   http://www.apache.org/licenses/LICENSE-2.0
 
Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and limitations under the License.
```
