import time
import logging

from spaceone.inventory.libs.manager import GoogleCloudManager
from spaceone.inventory.libs.schema.base import ReferenceModel
from spaceone.inventory.connector.cloud_sql.instance import CloudSQLInstanceConnector
from spaceone.inventory.model.cloud_sql.instance.cloud_service_type import (
    CLOUD_SERVICE_TYPES,
)
from spaceone.inventory.model.cloud_sql.instance.cloud_service import (
    Instance,
    InstanceResource,
    InstanceResponse,
)
from spaceone.inventory.model.cloud_sql.instance.data import Database, User

_LOGGER = logging.getLogger(__name__)


class CloudSQLManager(GoogleCloudManager):
    connector_name = "CloudSQLInstanceConnector"
    cloud_service_types = CLOUD_SERVICE_TYPES

    def collect_cloud_service(self, params):
        _LOGGER.debug("** Cloud SQL START **")
        start_time = time.time()
        """
        Args:
            params:
                - options
                - schema
                - secret_data
                - filter
                - zones
        Response:
            CloudServiceResponse/ErrorResourceResponse
        """

        collected_cloud_services = []
        error_responses = []
        instance_name = ""
        secret_data = params["secret_data"]
        project_id = secret_data["project_id"]

        ##################################
        # 0. Gather All Related Resources
        # List all information through connector
        ##################################
        cloud_sql_conn: CloudSQLInstanceConnector = self.locator.get_connector(
            self.connector_name, **params
        )
        instances = cloud_sql_conn.list_instances()

        for instance in instances:
            try:
                ##################################
                # 1. Set Basic Information
                ##################################
                instance_name = instance["name"]
                # stackdriver = self._get_stackdriver(project, instance_name)
                # Get Databases & Users, If SQL instance is not available skip, Database/User check.
                # Otherwise, It occurs error while list databases, list users.
                if self._check_sql_instance_is_available(instance):
                    databases = cloud_sql_conn.list_databases(instance_name)
                    users = cloud_sql_conn.list_users(instance_name)
                else:
                    databases = []
                    users = []

                ##################################
                # 2. Make Base Data
                ##################################
                monitoring_resource_id = f"{project_id}:{instance_name}"
                google_cloud_monitoring_filters = [
                    {
                        "key": "resource.labels.database_id",
                        "value": monitoring_resource_id,
                    }
                ]

                instance.update(
                    {
                        "google_cloud_monitoring": self.set_google_cloud_monitoring(
                            project_id,
                            "cloudsql.googleapis.com/database",
                            monitoring_resource_id,
                            google_cloud_monitoring_filters,
                        ),
                        "display_state": self._get_display_state(instance),
                        "databases": self._get_databases(databases),
                        "users": self._get_users(users),
                        "stats": {
                            "database_count": len(databases),
                            "user_count": len(users),
                        },
                    }
                )

                instance.update(
                    {
                        "google_cloud_logging": self.set_google_cloud_logging(
                            "CloudSQL", "Instance", project_id, monitoring_resource_id
                        )
                    }
                )

                # No labels!!
                instance_data = Instance(instance, strict=False)

                ##################################
                # 3. Make Return Resource
                ##################################
                instance_resource = InstanceResource(
                    {
                        "name": instance_name,
                        "account": project_id,
                        "region_code": instance["region"],
                        "data": instance_data,
                        "reference": ReferenceModel(instance_data.reference()),
                    }
                )

                ##################################
                # 4. Make Collected Region Code
                ##################################
                self.set_region_code(instance["region"])

                ##################################
                # 5. Make Resource Response Object
                # List of InstanceResponse Object
                ##################################
                collected_cloud_services.append(
                    InstanceResponse({"resource": instance_resource})
                )
            except Exception as e:
                _LOGGER.error(f"[collect_cloud_service] => {e}", exc_info=True)
                # Database Instance name is key(= instance_id)
                error_response = self.generate_resource_error_response(
                    e, "CloudSQL", "Instance", instance_name
                )
                error_responses.append(error_response)

        _LOGGER.debug(f"** Cloud SQL Finished {time.time() - start_time} Seconds **")
        return collected_cloud_services, error_responses

    # Check SQL Instance status
    def _check_sql_instance_is_available(self, instance):
        power_state = self._get_display_state(instance)
        create_state = instance.get("state", "")

        if create_state == "RUNNABLE" and power_state == "RUNNING":
            return True
        else:
            instance_name = instance.get("name", "")
            _LOGGER.debug(
                f"[_check_sql_instance_is_available] instance {instance_name} is not available"
            )
            return False

    # SQL Instance power status
    @staticmethod
    def _get_display_state(instance):
        activation_policy = instance.get("settings", {}).get(
            "activationPolicy", "UNKNOWN"
        )

        if activation_policy in ["ALWAYS"]:
            if instance.get("state") == "PENDING_CREATE":
                return "CREATING"
            elif instance.get("state") == "RUNNABLE":
                return "RUNNING"
        elif activation_policy in ["NEVER"]:
            return "STOPPED"
        elif activation_policy in ["ON_DEMAND"]:
            return "ON-DEMAND"

        return "UNKNOWN"

    @staticmethod
    def _get_databases(databases):
        # Convert database list(dict) -> list(database object)
        list_databases = []
        for database in databases:
            list_databases.append(Database(database, strict=False))

        return list_databases

    @staticmethod
    def _get_users(users):
        # Convert users list(dict) -> list(user object)
        list_users = []
        for user in users:
            user_obj = User(user, strict=False)
            list_users.append(user_obj)
        # list_users = [User(user, strict=False) for user in users]

        return list_users
