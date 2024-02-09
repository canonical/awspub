Architecture
============

`awspub` has some architectural choices which are important to know:

* image names need to be unique within a used account. `awspub` does
  detect if an image already exists by querying available images
  by name. If the name doesn't exist, it will create the image. If the
  name exists, it will use that image. If the name exist multiple times
  it will throw an exception.
* images will not be modified. so if a configuration changes it parameters
  for an image and the image already exists, the parameters will not
  be changed on EC2 (also most parameters can't be changed anyway for an
  image on EC2).
* snapshots are tracked by a sha256sum of the underlying source file (usually
  a .vmdk file). Some configration parameters (`separate_snapshot` and
  `billing_products`) do adjust that sha256sum to make it unique for the
  combination of source .vmdk file and config options.
* only EBS (no instance-store) and HVM (no PV) are supported.
