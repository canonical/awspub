How to use the API
==================

`awspub` provides a high-level API which can be used
to create and publish images.

Assuming there is a configuration file and a configuration file mapping:

.. code-block::

   import awspub
   awspub.create("config.yaml", "mapping.yaml")
   awspub.public("config.yaml", "mapping.yaml")
