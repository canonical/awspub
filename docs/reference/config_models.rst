Reference for configuration
===========================

This is the documentation for the pydantic models which are
use for config validation.

.. autopydantic_model:: awspub.configmodels.ConfigModel
   :model-show-json: True
   :model-show-config-summary: True

.. autopydantic_model:: awspub.configmodels.ConfigS3Model
   :model-show-json: True
   :model-show-config-summary: True

.. autopydantic_model:: awspub.configmodels.ConfigSourceModel
   :model-show-json: True
   :model-show-config-summary: True

.. autopydantic_model:: awspub.configmodels.ConfigSnapshotModel
   :model-show-json: True
   :model-show-config-summary: True

Direct creation requires ``snapshot.region`` to select the initial snapshot
region. The ``s3`` section can be omitted: direct mode makes no S3 calls,
including for image and SNS region discovery. Existing direct-mode configurations
must add ``snapshot.region``; a configured S3 bucket is not used as a fallback.
``images.<name>.regions`` still controls the destination regions for copying
snapshots and registering AMIs.

Import creation (the default) still requires ``s3.bucket_name`` and uses the
bucket's region, regardless of ``snapshot.region``. The CLI option
``--upload-multipart-concurrency`` applies only to import mode.

With ``snapshot.creation: direct``, the source can be a raw disk image or a
single-file sparse VMDK (``monolithicSparse`` or ``streamOptimized``).
Descriptor-based VMDKs, including split images, are rejected rather than
treated as raw disk data. Convert unsupported layouts to raw before publishing.
Truncated compressed grains and grains that expand beyond the declared grain
size are rejected. All-zero blocks, including a partial final block, are skipped.

.. autopydantic_model:: awspub.configmodels.ConfigImageModel
   :model-show-json: True
   :model-show-config-summary: True

.. autopydantic_model:: awspub.configmodels.ConfigImageMarketplaceModel
   :model-show-json: True
   :model-show-config-summary: True

.. autopydantic_model:: awspub.configmodels.ConfigImageMarketplaceSecurityGroupModel
   :model-show-json: True
   :model-show-config-summary: True

.. autopydantic_model:: awspub.configmodels.ConfigImageSNSNotificationModel
   :model-show-json: True
   :model-show-config-summary: True
