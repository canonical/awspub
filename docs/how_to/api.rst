How to use the API
==================

`awspub` provides a high-level API which can be used
to create and publish images.

Assuming there is a configuration file and a configuration file mapping:

.. code-block::

   import awspub
   awspub.create("config.yaml", "mapping.yaml")
   awspub.publish("config.yaml", "mapping.yaml")

To request Marketplace versions for existing images without public visibility,
SSM, or SNS publication, select the release image group explicitly:

.. code-block:: python

   from pathlib import Path

   awspub.publish_marketplace(Path("config.yaml"), Path("mapping.yaml"), "release")

To perform the other publication actions separately, exclude Marketplace when
calling ``publish``:

.. code-block:: python

   awspub.publish(Path("config.yaml"), Path("mapping.yaml"), "release", skip_marketplace=True)

The default remains full publication when ``skip_marketplace`` is omitted.
