import time
import logging

from spaceone.inventory.libs.manager import GoogleCloudManager
from spaceone.inventory.libs.schema.base import ReferenceModel
from spaceone.inventory.connector.compute_engine.snapshot import SnapshotConnector
from spaceone.inventory.model.compute_engine.snapshot.cloud_service_type import (
    CLOUD_SERVICE_TYPES,
)
from spaceone.inventory.model.compute_engine.snapshot.cloud_service import (
    SnapshotResource,
    SnapshotResponse,
)
from spaceone.inventory.model.compute_engine.snapshot.data import Snapshot

_LOGGER = logging.getLogger(__name__)


class SnapshotManager(GoogleCloudManager):
    connector_name = "SnapshotConnector"
    cloud_service_types = CLOUD_SERVICE_TYPES

    def collect_cloud_service(self, params):
        _LOGGER.debug(f"** Snapshot START **")
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
        snapshot_id = ""

        secret_data = params["secret_data"]
        project_id = secret_data["project_id"]

        ##################################
        # 0. Gather All Related Resources
        # List all information through connector
        ##################################
        snapshot_conn: SnapshotConnector = self.locator.get_connector(
            self.connector_name, **params
        )

        # Get lists that relate with snapshots through Google Cloud API
        snapshots = snapshot_conn.list_snapshot()

        for snapshot in snapshots:
            try:
                ##################################
                # 1. Set Basic Information
                ##################################
                snapshot_id = snapshot.get("id")
                region = self.get_matching_region(snapshot.get("storageLocations"))

                labels = self.convert_labels_format(snapshot.get("labels", {}))
                snapshot.update(
                    {
                        "project": secret_data["project_id"],
                        "disk": self.get_disk_info(snapshot),
                        "creation_type": (
                            "Scheduled" if snapshot.get("autoCreated") else "Manual"
                        ),
                        "encryption": self.get_disk_encryption_type(
                            snapshot.get("snapshotEncryptionKey")
                        ),
                        "labels": labels,
                    }
                )

                ##################################
                # 2. Make Base Data
                ##################################
                snapshot_data = Snapshot(snapshot, strict=False)
                _name = snapshot_data.get("name", "")

                ##################################
                # 3. Make Return Resource
                ##################################
                # labels -> tags
                snapshots_resource = SnapshotResource(
                    {
                        "name": _name,
                        "account": project_id,
                        "region_code": region.get("region_code"),
                        "data": snapshot_data,
                        "tags": labels,
                        "reference": ReferenceModel(snapshot_data.reference()),
                    }
                )

                ##################################
                # 4. Make Collected Region Code
                ##################################
                self.set_region_code(region.get("region_code"))

                ##################################
                # 5. Make Resource Response Object
                # List of LoadBalancingResponse Object
                ##################################
                collected_cloud_services.append(
                    SnapshotResponse({"resource": snapshots_resource})
                )
            except Exception as e:
                _LOGGER.error(f"[collect_cloud_service] => {e}", exc_info=True)
                error_response = self.generate_resource_error_response(
                    e, "ComputeEngine", "Snapshot", snapshot_id
                )
                error_responses.append(error_response)

        _LOGGER.debug(f"** SnapShot Finished {time.time() - start_time} Seconds **")
        return collected_cloud_services, error_responses

    def get_matching_region(self, svc_location):
        region_code = svc_location[0] if svc_location else "global"
        matched_info = self.match_region_info(region_code)
        return (
            {"region_code": region_code, "location": "regional"}
            if matched_info
            else {"region_code": "global", "location": "multi"}
        )

    def get_disk_info(self, snapshot):
        """
        source_disk = StringType()
        source_disk_display = StringType()
        source_disk_id = StringType()
        diskSizeGb = IntType()
        disk_size_display = StringType()
        storage_bytes = IntType()
        storage_bytes_display = StringType()
        """
        disk_gb = snapshot.get("diskSizeGb", 0.0)
        st_byte = snapshot.get("storageBytes", 0)
        size = self._get_bytes(int(disk_gb))
        return {
            "source_disk": snapshot.get("sourceDisk", ""),
            "source_disk_display": self.get_param_in_url(
                snapshot.get("sourceDisk", ""), "disks"
            ),
            "source_disk_id": snapshot.get("sourceDiskId", ""),
            "disk_size": float(size),
            "storage_bytes": int(st_byte),
        }

    @staticmethod
    def _get_bytes(number):
        return 1024 * 1024 * 1024 * number
