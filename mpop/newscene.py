#!/usr/bin/env python
# -*- coding: utf-8 -*-

# Copyright (c) 2015

# Author(s):

#   Martin Raspaud <martin.raspaud@smhi.se>
#   David Hoese <david.hoese@ssec.wisc.edu>

# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

"""Scene objects to hold satellite data.
"""

import numbers
import ConfigParser
import os
import trollsift
import glob
import fnmatch
import numpy as np
import imp
import mpop.satin
from mpop.imageo.geo_image import GeoImage
from mpop.utils import debug_on
debug_on()
from mpop.projectable import Projectable, InfoObject
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

class IncompatibleAreas(StandardError):
    pass

class Scene(InfoObject):

    def __init__(self, filenames=None, ppp_config_dir=None, **info):
        """platform_name=None, sensor=None, start_time=None, end_time=None,
        """
        # Get PPP_CONFIG_DIR
        self.ppp_config_dir = ppp_config_dir or os.environ.get("PPP_CONFIG_DIR", '.')
        # Set the PPP_CONFIG_DIR in the environment in case it's used else where in pytroll
        logger.debug("Setting 'PPP_CONFIG_DIR' to '%s'", self.ppp_config_dir)
        os.environ["PPP_CONFIG_DIR"] = self.ppp_config_dir

        InfoObject.__init__(self, **info)
        self.projectables = {}
        if "sensor" in self.info:
            config = ConfigParser.ConfigParser()
            config.read(os.path.join(self.ppp_config_dir, "mpop.cfg"))
            try:
                config_file = config.get("readers", self.info["sensor"])
            except ConfigParser.NoOptionError:
                raise NameError("No configuration file provided in mpop.cfg for sensor " + self.info["sensor"])
            if not os.path.exists(config_file):
                config_file = os.path.join(self.ppp_config_dir, config_file)

            reader_info = self._read_config(config_file)
            if filenames is None:
                reader_info["filenames"] = self.get_filenames(reader_info)
            else:
                self.assign_matching_files(reader_info, *filenames)

        elif filenames is not None:
            self.find_readers(*filenames)

        self.products = {}

    def get_filenames(self, reader_info):
        """Get the filenames from disk given the patterns in *reader_info*.
        This assumes that the scene info contains start_time at least (possibly end_time too).
        """
        epoch = datetime(1950, 1, 1)
        filenames = []
        for pattern in reader_info["file_patterns"]:
            parser = trollsift.parser.Parser(pattern)
            # FIXME: what if we are browsing a huge archive ?
            info = self.info.copy()
            info.pop("start_time", None)
            info.pop("end_time", None)
            info.pop("creation_time", None)
            for filename in glob.iglob(parser.globify(info)):
                metadata = parser.parse(filename)
                if "end_time" in self.info:
                    # get the data within the time interval
                    end_time = metadata.get("end_time", epoch)
                    if ((self.info["start_time"] <= metadata["start_time"] <= self.info["end_time"]) or
                            (self.info["start_time"] <=  end_time <= self.info["end_time"])):
                        filenames.append(filename)
                else:
                    # get the data containing start_time
                    if "end_time" in metadata and metadata["start_time"] <= self.info["start_time"] <= metadata["end_time"]:
                        filenames.append(filename)
                    elif metadata["start_time"] == self.info["start_time"]:
                        filenames.append(filename)
                        break
        return filenames







    def add_product(self, name, obj):
        self.products[name] = obj

    def _read_config(self, cfg_file):
        conf = ConfigParser.RawConfigParser()

        if not os.path.exists(cfg_file):
            raise IOError("No such file: " + cfg_file)

        conf.read(cfg_file)
        file_patterns = []
        reader_format = None
        # Only one reader: section per config file
        for section in conf.sections():
            if section.startswith("reader:"):
                reader_info = dict(conf.items(section))
                reader_info["file_patterns"] = reader_info.setdefault("file_patterns", "").split(",")
                try:
                    reader_format = reader_info["format"]
                except KeyError:
                    break
                self.info.setdefault("reader_info", {})[reader_format] = reader_info
                file_patterns.extend(reader_info["file_patterns"])
            else:
                try:
                    file_patterns.extend(conf.get(section, "file_patterns").split(","))
                except ConfigParser.NoOptionError:
                    pass
        if reader_format is None:
            raise ValueError("Malformed config file %s: missing reader format"%cfg_file)
        reader_info["file_patterns"] = file_patterns
        reader_info["config_file"] = cfg_file
        return reader_info

            #     wl = [float(elt)
            #           for elt in conf.get(section, "frequency").split(",")]
            #     res = conf.getint(section, "resolution")
            #     uid = conf.get(section, "name")
            #     new_chn = Projectable(wavelength_range=wl,
            #                           resolution=res,
            #                           uid=uid,
            #                           sensor=instrument,
            #                           platform_name=self.info["platform_name"]
            #                           )
            #     self.projectables[uid] = new_chn
            # # for method in get_custom_composites(instrument):
            # #    self.add_method_to_instance(method)

    def __str__(self):
        return "\n".join((str(prj) for prj in self.projectables.values()))

    def __iter__(self):
        return iter(self.projectables.values())

    def __getitem__(self, key):
        # get by wavelength
        if isinstance(key, numbers.Number):
            channels = [chn for chn in self.projectables.values()
                        if("wavelength_range" in chn.info and
                           chn.info["wavelength_range"][0] <= key and
                           chn.info["wavelength_range"][2] >= key)]
            channels = sorted(channels,
                              lambda ch1, ch2:
                              cmp(abs(ch1.info["wavelength_range"][1] - key),
                                  abs(ch2.info["wavelength_range"][1] - key)))

            if not channels:
                raise KeyError("Can't find any projectable at %gum" % key)
            return channels[0]
        # get by name
        else:
            return self.projectables[key]
        raise KeyError("No channel corresponding to " + str(key) + ".")

    def __setitem__(self, key, value):
        # TODO: Set item in projectables dictionary(!) and make sure metadata in info is changed to new name
        # TODO: Copy the projectable? No, don't copy
        raise NotImplementedError()

    def __delitem__(self, key):
        # TODO: Delete item from projectables dictionary(!)
        raise NotImplementedError()

    def __contains__(self, uid):
        return uid in self.projectables

    def assign_matching_files(self, reader_info, *files):
        files = list(files)
        for file_pattern in reader_info["file_patterns"]:
            pattern = trollsift.globify(file_pattern)
            for filename in list(files):
                if fnmatch.fnmatch(os.path.basename(filename),
                                   os.path.basename(pattern)):
                    self.info.setdefault("reader_info", {}).setdefault(reader_info["format"], reader_info)
                    reader_info.setdefault("filenames", []).append(filename)
                    files.remove(filename)


    def find_readers(self, *files):
        """Find the reader info for the provided *files*.
        """
        for config_file in glob.glob(os.path.join(self.ppp_config_dir, "*.cfg")):
            reader_info = self._read_config(config_file)

            files = self.assign_matching_files(reader_info, *files)

            if not files:
                break
        if files:
            raise IOError("Don't know how to open the following files: %s"%str(files))

    # def _find_reader_format(self):
    #     # get reader
    #     print self.info["reader_info"]
    #     for reader, reader_config in self.info["reader_info"].items():
    #         for pattern in reader_config["file_patterns"]:
    #             pattern = trollsift.globify(pattern)
    #             print pattern
    #             if fnmatch.fnmatch(os.path.basename(self.filenames[0]),
    #                                os.path.basename(pattern)):
    #                 return reader
    #     raise RuntimeError("No reader found for filename %s" % (self.filenames[0],))

    def read(self, *projectable_names, **kwargs):
        self.info["wishlist"] = projectable_names

        # FIXME: Assumes we found a reader in the previous loop

        for reader_info in self.info["reader_info"].values():
            reader_module, reading_element = reader_info["format"].rsplit(".", 1)
            reader = "mpop.satin." + reader_module

            try:
                # Look for builtin reader
                imp.find_module(reader_module, mpop.satin.__path__)
            except ImportError:
                # Look for custom reader
                loader = __import__(reader_module, globals(),
                                    locals(), [reading_element])
            else:
                loader = __import__(reader, globals(),
                                    locals(), [reading_element])

            loader = getattr(loader, reading_element)
            reader_instance = loader(self, **reader_info)
            setattr(self, loader.pformat + "_reader", reader_instance)

            # compute the depencies to load from file
            pnames = set(projectable_names)
            needed_bands = None
            rerun = True
            while rerun:
                rerun = False
                needed_bands = set()
                for band in pnames:
                    if band in self.products:
                        needed_bands |= set(self.products[band].prerequisites)
                        rerun = True
                    else:
                        needed_bands.add(band)
                pnames = needed_bands

            reader_instance.load(set(pnames), filenames=reader_info["filenames"])

    def compute(self, *requirements):
        if not requirements:
            requirements = self.info["wishlist"]
        for requirement in requirements:
            if requirement not in self.products:
                continue
            if requirement in self.projectables:
                continue
            self.compute(*self.products[requirement].prerequisites)
            try:
                self.projectables[requirement] = self.products[requirement](scn)
            except IncompatibleAreas:
                for uid, projectable in self.projectables.item():
                    if uid in self.products[requirement].prerequisites:
                        projectable.info["keep"] = True

    def unload(self):
        to_del = [uid for uid, projectable in self.projectables.items()
                  if uid not in self.info["wishlist"] and
                  not projectable.info.get("keep", False)]
        for uid in to_del:
            del self.projectables[uid]

    def load(self, *wishlist, **kwargs):
        self.read(*wishlist, **kwargs)
        if kwargs.get("compute", True):
            self.compute()
        if kwargs.get("unload", True):
            self.unload()

    def resample(self, destination, channels=None, **kwargs):
        """Resample the projectables and return a new scene.
        """
        new_scn = Scene()
        new_scn.info = self.info.copy()
        for uid, projectable in self.projectables.items():
            logger.debug("Resampling %s", uid)
            if channels and not uid in channels:
                continue
            new_scn.projectables[uid] = projectable.resample(destination, **kwargs)
        return new_scn

    def images(self):
        for uid, projectable in self.projectables.items():
            if uid in self.info["wishlist"]:
                yield projectable.to_image()


class CompositeBase(InfoObject):

    def __init__(self, **kwargs):
        InfoObject.__init__(self, **kwargs)
        self.prerequisites = []

    def __call__(self, scene):
        raise NotImplementedError()


class VIIRSFog(CompositeBase):

    def __init__(self, uid="fog", **kwargs):
        CompositeBase.__init__(self, **kwargs)
        self.uid = uid
        self.prerequisites = ["I04", "I05"]

    def __call__(self, scene):
        fog = scene["I05"] - scene["I04"]
        fog.info["area"] = scene["I05"].info["area"]
        fog.info["uid"] = self.uid
        return fog


class VIIRSTrueColor(CompositeBase):

    def __init__(self, uid="true_color", image_config=None, **kwargs):
        default_image_config={"mode": "RGB",
                              "stretch": "log"}
        if image_config is not None:
            default_image_config.update(image_config)

        CompositeBase.__init__(self, **kwargs)
        self.uid = uid
        self.prerequisites = ["M02", "M04", "M05"]
        self.info["image_config"] = default_image_config

    def __call__(self, scene):
        # raise IncompatibleAreas
        return Projectable(uid=self.uid,
                           data=np.concatenate(
                               ([scene["M05"].data], [scene["M04"].data], [scene["M02"].data]), axis=0),
                           area=scene["M05"].info["area"],
                           time_slot=scene.info["start_time"],
                           **self.info)



import unittest


class TestScene(unittest.TestCase):

    def test_config_reader(self):
        "Check config reading"
        scn = Scene()
        scn._read_config(
            "/home/a001673/usr/src/newconfig/Suomi-NPP.cfg")
        self.assertTrue("DNB" in scn)

    def test_channel_get(self):
        scn = Scene()
        scn._read_config(
            "/home/a001673/usr/src/newconfig/Suomi-NPP.cfg")
        self.assertEqual(scn[0.67], scn["M05"])

    def test_metadata(self):
        scn = Scene()
        scn._read_config(
            "/home/a001673/usr/src/newconfig/Suomi-NPP.cfg")
        self.assertEqual(scn.info["platform_name"], "Suomi-NPP")

    def test_open(self):
        scn = Scene()
        scn.find_readers(
            "/home/a001673/data/satellite/Suomi-NPP/viirs/lvl1b/2015/04/20/SDR/SVM02_npp_d20150420_t0536333_e0537575_b18015_c20150420054512262557_cspp_dev.h5")

        self.assertEqual(scn.info["platform_name"], "Suomi-NPP")

        self.assertRaises(IOError, scn.find_readers, "bla")


class TestProjectable(unittest.TestCase):
    pass

if __name__ == '__main__':
    scn = Scene()
    #scn._read_config("/home/a001673/usr/src/pytroll-config/etc/Suomi-NPP.cfg")

    myfiles = ["/home/a001673/data/satellite/Suomi-NPP/viirs/lvl1b/2015/04/20/SDR/SVM16_npp_d20150420_t0536333_e0537575_b18015_c20150420054512738521_cspp_dev.h5",
               "/home/a001673/data/satellite/Suomi-NPP/viirs/lvl1b/2015/04/20/SDR/GMTCO_npp_d20150420_t0536333_e0537575_b18015_c20150420054511332482_cspp_dev.h5"]

    myfiles = ["/home/a001673/data/satellite/Suomi-NPP/viirs/lvl1b/2015/03/11/SDR/SVI01_npp_d20150311_t1125112_e1126354_b17451_c20150311113328862761_cspp_dev.h5",
               "/home/a001673/data/satellite/Suomi-NPP/viirs/lvl1b/2015/03/11/SDR/SVI02_npp_d20150311_t1125112_e1126354_b17451_c20150311113328951540_cspp_dev.h5",
               "/home/a001673/data/satellite/Suomi-NPP/viirs/lvl1b/2015/03/11/SDR/SVI03_npp_d20150311_t1125112_e1126354_b17451_c20150311113329042562_cspp_dev.h5",
               "/home/a001673/data/satellite/Suomi-NPP/viirs/lvl1b/2015/03/11/SDR/SVI04_npp_d20150311_t1125112_e1126354_b17451_c20150311113329143755_cspp_dev.h5",
               "/home/a001673/data/satellite/Suomi-NPP/viirs/lvl1b/2015/03/11/SDR/SVI05_npp_d20150311_t1125112_e1126354_b17451_c20150311113329234947_cspp_dev.h5",
               "/home/a001673/data/satellite/Suomi-NPP/viirs/lvl1b/2015/03/11/SDR/SVM01_npp_d20150311_t1125112_e1126354_b17451_c20150311113329326838_cspp_dev.h5",
               "/home/a001673/data/satellite/Suomi-NPP/viirs/lvl1b/2015/03/11/SDR/SVM02_npp_d20150311_t1125112_e1126354_b17451_c20150311113329360063_cspp_dev.h5",
               "/home/a001673/data/satellite/Suomi-NPP/viirs/lvl1b/2015/03/11/SDR/SVM03_npp_d20150311_t1125112_e1126354_b17451_c20150311113329390738_cspp_dev.h5",
               "/home/a001673/data/satellite/Suomi-NPP/viirs/lvl1b/2015/03/11/SDR/SVM04_npp_d20150311_t1125112_e1126354_b17451_c20150311113329427332_cspp_dev.h5",
               "/home/a001673/data/satellite/Suomi-NPP/viirs/lvl1b/2015/03/11/SDR/SVM05_npp_d20150311_t1125112_e1126354_b17451_c20150311113329464787_cspp_dev.h5",
               "/home/a001673/data/satellite/Suomi-NPP/viirs/lvl1b/2015/03/11/SDR/SVM06_npp_d20150311_t1125112_e1126354_b17451_c20150311113329503232_cspp_dev.h5",
               "/home/a001673/data/satellite/Suomi-NPP/viirs/lvl1b/2015/03/11/SDR/SVM07_npp_d20150311_t1125112_e1126354_b17451_c20150311113330249624_cspp_dev.h5",
               "/home/a001673/data/satellite/Suomi-NPP/viirs/lvl1b/2015/03/11/SDR/SVM08_npp_d20150311_t1125112_e1126354_b17451_c20150311113329572000_cspp_dev.h5",
               "/home/a001673/data/satellite/Suomi-NPP/viirs/lvl1b/2015/03/11/SDR/SVM09_npp_d20150311_t1125112_e1126354_b17451_c20150311113329602050_cspp_dev.h5",
               "/home/a001673/data/satellite/Suomi-NPP/viirs/lvl1b/2015/03/11/SDR/SVM10_npp_d20150311_t1125112_e1126354_b17451_c20150311113329632503_cspp_dev.h5",
               "/home/a001673/data/satellite/Suomi-NPP/viirs/lvl1b/2015/03/11/SDR/SVM11_npp_d20150311_t1125112_e1126354_b17451_c20150311113329662488_cspp_dev.h5",
               "/home/a001673/data/satellite/Suomi-NPP/viirs/lvl1b/2015/03/11/SDR/SVM12_npp_d20150311_t1125112_e1126354_b17451_c20150311113329692444_cspp_dev.h5",
               "/home/a001673/data/satellite/Suomi-NPP/viirs/lvl1b/2015/03/11/SDR/SVM13_npp_d20150311_t1125112_e1126354_b17451_c20150311113329722069_cspp_dev.h5",
               "/home/a001673/data/satellite/Suomi-NPP/viirs/lvl1b/2015/03/11/SDR/SVM14_npp_d20150311_t1125112_e1126354_b17451_c20150311113329767340_cspp_dev.h5",
               "/home/a001673/data/satellite/Suomi-NPP/viirs/lvl1b/2015/03/11/SDR/SVM15_npp_d20150311_t1125112_e1126354_b17451_c20150311113329796873_cspp_dev.h5",
               "/home/a001673/data/satellite/Suomi-NPP/viirs/lvl1b/2015/03/11/SDR/SVM16_npp_d20150311_t1125112_e1126354_b17451_c20150311113329826626_cspp_dev.h5",
               "/home/a001673/data/satellite/Suomi-NPP/viirs/lvl1b/2015/03/11/SDR/GDNBO_npp_d20150311_t1125112_e1126354_b17451_c20150311113327046285_cspp_dev.h5",
               "/home/a001673/data/satellite/Suomi-NPP/viirs/lvl1b/2015/03/11/SDR/GITCO_npp_d20150311_t1125112_e1126354_b17451_c20150311113327852159_cspp_dev.h5",
               "/home/a001673/data/satellite/Suomi-NPP/viirs/lvl1b/2015/03/11/SDR/GMTCO_npp_d20150311_t1125112_e1126354_b17451_c20150311113328505792_cspp_dev.h5",
               "/home/a001673/data/satellite/Suomi-NPP/viirs/lvl1b/2015/03/11/SDR/SVDNB_npp_d20150311_t1125112_e1126354_b17451_c20150311113326791425_cspp_dev.h5",
               ]

    scn = Scene(filenames=myfiles)

    scn.add_product("fog", VIIRSFog())
    scn.add_product("true_color", VIIRSTrueColor())

    scn.load("fog", "I01", "M16", "true_color")

    #img = scn["true_color"].to_image()
    #img.show()

    from mpop.projector import get_area_def
    eurol = get_area_def("eurol")
    newscn = scn.resample(eurol, radius_of_influence=2000)

    # unittest.main()

    #########
    #
    # this part can be put in a user-owned file

    # def nice_composite(self, some_param=None):
    #     # do something here
    #     return self

    # nice_composite.prerequisites = ["i05", "dnb", "fog"]

    # scn.add_product(nice_composite)

    # def fog(self):
    #     return self["i05"] - self["i04"]

    # fog.prerequisites = ["i05", "i04"]

    # scn.add_product(fog)

    # # end of this part
    # #
    # ##########

    # # nice composite uses fog
    # scn.load("nice_composite", area="europe")

    # scn.products.nice_composite