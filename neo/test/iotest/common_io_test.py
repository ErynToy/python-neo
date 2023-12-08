"""
Common tests for IOs:
 * check presence of all necessary attr
 * check types
 * write/read consistency

See BaseTestIO.


The public URL is in url_for_tests.

To deposit new testing files, please create a account at
gin.g-node.org and upload files at NeuralEnsemble/ephy_testing_data
data repo.

"""

__test__ = False

import os
import inspect
import unittest
import pathlib

from neo.core import Block, Segment
from neo.io.basefromrawio import BaseFromRaw
from neo.test.tools import (assert_same_sub_schema,
                            assert_neo_object_is_compliant,
                            assert_sub_schema_is_lazy_loaded)

from neo.test.rawiotest.tools import can_use_network
from neo.test.rawiotest.common_rawio_test import repo_for_test
from neo.utils import (download_dataset, get_local_testing_data_folder)
from neo import list_candidate_ios

try:
    import datalad
    HAVE_DATALAD = True
except:
    HAVE_DATALAD = False

from neo.test.iotest.tools import (close_object_safe, create_generic_io_object,
                                   create_generic_reader,
                                   get_test_file_full_path,
                                   iter_generic_io_objects,
                                   iter_generic_readers, iter_read_objects,
                                   read_generic,
                                   write_generic)

from neo.test.generate_datasets import generate_from_supported_objects


class BaseTestIO:
    """
    This class defines common tests for all IOs.

    Several strategies:
      * for IO able to read write : test_write_then_read
      * for IO able to read write with hash conservation (optional):
        test_read_then_write
      * for all IOs : test_assert_read_neo_object_is_compliant
        2 cases:
          * files are at G-node and downloaded
          * files are generated by MyIO.write()


    Note: When inheriting this class use it as primary superclass in
    combination with the unittest.TestCase as a 2nd superclass, e.g.
    `NewIOTestClass(BaseTestIO, unittest.TestCase):`

    """
    # __test__ = False

    # all IO test need to modify this:
    ioclass = None  # the IOclass to be tested

    entities_to_test = []  # list of files to test compliance
    entities_to_download = []  # when files are at gin

    # when reading then writing produces files with identical hashes
    hash_conserved_when_write_read = False
    # when writing then reading creates an identical neo object
    read_and_write_is_bijective = True

    # allow environment to tell avoid using network
    use_network = can_use_network()

    local_test_dir = get_local_testing_data_folder()

    def setUp(self):
        """
        This is run once per test case
        """
        pass

    @classmethod
    def setUpClass(cls, *args, **kwargs):
        """
        This is run once per test class instance
        """
        if cls == BaseTestIO:
            cls.run = lambda self, *args, **kwargs: None
            return

        super(BaseTestIO, cls).setUpClass()
        cls.default_arguments = []
        cls.default_keyword_arguments = {}
        cls.higher = cls.ioclass.supported_objects[0]
        cls.shortname = cls.ioclass.__name__.lower().rstrip('io')
        # these objects can both be written and read
        cls.io_readandwrite = list(set(cls.ioclass.readable_objects) &
                                    set(cls.ioclass.writeable_objects))
        # these objects can be either written or read
        cls.io_readorwrite = list(set(cls.ioclass.readable_objects) |
                                   set(cls.ioclass.writeable_objects))
        if HAVE_DATALAD:
            for remote_path in cls.entities_to_download:
                download_dataset(repo=repo_for_test, remote_path=remote_path)

            cls.files_generated = []
            cls.generate_files_for_io_able_to_write()

            # be careful cls.entities_to_test is class attributes
            cls.files_to_test = [cls.get_local_path(e) for e in cls.entities_to_test]
        else:
            cls.files_to_test = []
            raise unittest.SkipTest("Requires datalad download of data from the web")

    @classmethod
    def able_to_write_or_read(cls, writeread=False, readwrite=False):
        """
        Return True if generalized writing or reading is possible.

        If writeread=True, return True if writing then reading is
        possible and produces identical neo objects.

        If readwrite=True, return True if reading then writing is possible
        and produces files with identical hashes.
        """
        # Find the highest object that is supported by the IO
        # Test only if it is a Block or Segment, and if it can both read
        # and write this object.
        if cls.higher not in cls.io_readandwrite:
            return False
        if cls.higher not in [Block, Segment]:
            return False

        # when io need external knowledge for writing or reading such as
        # sampling_rate (RawBinaryIO...) the test is too complex to design
        # generically.
        if (cls.higher in cls.ioclass.read_params and
                len(cls.ioclass.read_params[cls.higher]) != 0):
            return False

        # handle cases where the test should write then read
        if writeread and not cls.read_and_write_is_bijective:
            return False

        # handle cases where the test should read then write
        if readwrite and not cls.hash_conserved_when_write_read:
            return False

        return True

    @staticmethod
    def get_local_base_folder():
        return get_local_testing_data_folder()

    @classmethod
    def get_local_path(cls, sub_path):
        root_local_path = cls.get_local_base_folder()
        local_path = root_local_path / sub_path
        # TODO later : remove the str when all IOs handle the pathlib.Path objects
        local_path = str(local_path)
        return local_path

    @classmethod
    def generic_io_object(cls, filename=None, return_path=False, clean=False):
        """
        Create an io object in a generic way that can work with both
        file-based and directory-based io objects.

        If filename is None, create a filename (default).

        If return_path is True, return the full path of the file along with
        the io object.  return ioobj, path.  Default is False.

        If clean is True, try to delete existing versions of the file
        before creating the io object.  Default is False.
        """
        return create_generic_io_object(ioclass=cls.ioclass,
                                        filename=filename,
                                        directory=cls.local_test_dir,
                                        return_path=return_path,
                                        clean=clean)

    def read_file(self, filename=None, return_path=False, clean=False,
                  target=None, readall=False, lazy=False):
        """
        Read from the specified filename.

        If filename is None, create a filename (default).

        If return_path is True, return the full path of the file along with
        the object.  return obj, path.  Default is False.

        If clean is True, try to delete existing versions of the file
        before creating the io object.  Default is False.

        If target is None, use the first supported_objects from ioobj
        If target is False, use the 'read' method.
        If target is the Block or Segment class, use read_block or
        read_segment, respectively.
        If target is a string, use 'read_'+target.

        The lazy parameter is passed to the reader.  Defaults is True.

        If readall is True, use the read_all_ method instead of the read_
        method. Default is False.
        """
        ioobj, path = self.generic_io_object(filename=filename,
                                             return_path=True, clean=clean)
        obj = read_generic(ioobj, target=target, lazy=lazy,
                           readall=readall, return_reader=False)

        if return_path:
            return obj, path
        return obj

    def write_file(self, obj=None, filename=None, return_path=False,
                   clean=False, target=None):
        """
        Write the target object to a file using the given neo io object ioobj.

        If filename is None, create a filename (default).

        If return_path is True, return the full path of the file along with
        the object.  return obj, path.  Default is False.

        If clean is True, try to delete existing versions of the file
        before creating the io object.  Default is False.

        If target is None, use the first supported_objects from ioobj
        If target is False, use the 'read' method.
        If target is the Block or Segment class, use read_block or
        read_segment, respectively.
        If target is a string, use 'read_'+target.

        obj is the object to write.  If obj is None, an object is created
        automatically for the io class.
        """
        ioobj, path = self.generic_io_object(filename=filename,
                                             return_path=True, clean=clean)
        obj = write_generic(ioobj, target=target, return_reader=False)

        if return_path:
            return obj, path
        return obj

    def iter_io_objects(self, return_path=False, clean=False):
        """
        Return an iterable over the io objects created from files_to_test

        If return_path is True, yield the full path of the file along with
        the io object.  yield ioobj, path  Default is False.

        If clean is True, try to delete existing versions of the file
        before creating the io object.  Default is False.
        """
        return iter_generic_io_objects(ioclass=self.ioclass,
                                       filenames=self.files_to_test,
                                       directory=self.local_test_dir,
                                       return_path=return_path,
                                       clean=clean)

    def iter_readers(self, target=None, readall=False,
                     return_path=False, return_ioobj=False, clean=False):
        """
        Return an iterable over readers created from files_to_test.

        If return_path is True, return the full path of the file along with
        the reader object.  return reader, path.

        If return_ioobj is True, return the io object as well as the reader.
        return reader, ioobj.  Default is False.

        If both return_path and return_ioobj is True,
        return reader, path, ioobj.  Default is False.

        If clean is True, try to delete existing versions of the file
        before creating the io object.  Default is False.

        If readall is True, use the read_all_ method instead of the
        read_ method. Default is False.
        """
        return iter_generic_readers(ioclass=self.ioclass,
                                    filenames=self.files_to_test,
                                    directory=self.local_test_dir,
                                    return_path=return_path,
                                    return_ioobj=return_ioobj,
                                    target=target,
                                    clean=clean,
                                    readall=readall)

    def iter_objects(self, target=None, return_path=False, return_ioobj=False,
                     return_reader=False, clean=False, readall=False,
                     lazy=False):
        """
        Iterate over objects read from the list of filenames in files_to_test.

        If target is None, use the first supported_objects from ioobj
        If target is False, use the 'read' method.
        If target is the Block or Segment class, use read_block or
        read_segment, respectively.
        If target is a string, use 'read_'+target.

        If return_path is True, yield the full path of the file along with
        the object.  yield obj, path.

        If return_ioobj is True, yield the io object as well as the object.
        yield obj, ioobj.  Default is False.

        If return_reader is True, yield the io reader function as well as the
        object. yield obj, reader.  Default is False.

        If some combination of return_path, return_ioobj, and return_reader
        is True, they are yielded in the order: obj, path, ioobj, reader.

        If clean is True, try to delete existing versions of the file
        before creating the io object.  Default is False.

        The lazy parameters is passed to the reader.  Defaults is True.

        If readall is True, use the read_all_ method instead of the read_
        method. Default is False.
        """
        return iter_read_objects(ioclass=self.ioclass,
                                 filenames=self.files_to_test,
                                 directory=self.local_test_dir,
                                 target=target,
                                 return_path=return_path,
                                 return_ioobj=return_ioobj,
                                 return_reader=return_reader,
                                 clean=clean, readall=readall,
                                 lazy=lazy)

    @classmethod
    def generate_files_for_io_able_to_write(cls):
        """
        Write files for use in testing.
        """
        cls.files_generated = []
        if not cls.able_to_write_or_read():
            return

        generate_from_supported_objects(cls.ioclass.supported_objects)

        ioobj, path = cls.generic_io_object(return_path=True, clean=True)
        if ioobj is None:
            return

        cls.files_generated.append(path)

        write_generic(ioobj, target=cls.higher)

        close_object_safe(ioobj)

    def test_write_then_read(self):
        """
        Test for IO that are able to write and read - here %s:
          1 - Generate a full schema with supported objects.
          2 - Write to a file
          3 - Read from the file
          4 - Check the hierachy
          5 - Check data

        Work only for IO for Block and Segment for the highest object
        (main cases).
        """ % self.ioclass.__name__

        if not self.able_to_write_or_read(writeread=True):
            return

        ioobj1 = self.generic_io_object(clean=True)

        if ioobj1 is None:
            return

        ob1 = write_generic(ioobj1, target=self.higher)
        close_object_safe(ioobj1)

        ioobj2 = self.generic_io_object()

        # Read the highest supported object from the file
        obj_reader = create_generic_reader(ioobj2, target=False)
        ob2 = obj_reader()[0]
        if self.higher == Segment:
            ob2 = ob2.segments[0]

        # some formats (e.g. elphy) do not support double floating
        # point spiketrains
        try:
            assert_same_sub_schema(ob1, ob2, True, 1e-8)
            assert_neo_object_is_compliant(ob1)
            assert_neo_object_is_compliant(ob2)
        # intercept exceptions and add more information
        except BaseException as exc:
            raise

        close_object_safe(ioobj2)

    def test_read_then_write(self):
        """
        Test for IO that are able to read and write, here %s:
         1 - Read a file
         2 Write object set in another file
         3 Compare the 2 files hash

        NOTE: TODO: Not implemented yet
        """ % self.ioclass.__name__

        if not self.able_to_write_or_read(readwrite=True):
            return
            # assert_file_contents_equal(a, b)

    def test_assert_read_neo_object_is_compliant(self):
        """
        Reading %s files in `files_to_test` produces compliant objects.

        Compliance test: neo.test.tools.assert_neo_object_is_compliant for
        lazy mode.
        """ % self.ioclass.__name__
        for obj, path in self.iter_objects(lazy=False, return_path=True):
            try:
                # Check compliance of the block
                assert_neo_object_is_compliant(obj)
            # intercept exceptions and add more information
            except BaseException as exc:
                exc.args += ('from %s' % os.path.basename(path), )
                raise

    def test_read_with_lazy_is_compliant(self):
        """
        Reading %s files in `files_to_test` with `lazy` is compliant.

        Test the reader with lazy = True.
        The schema must contain proxy objects.

        """ % self.ioclass.__name__
        # This is for files presents at G-Node or generated
        if self.ioclass.support_lazy:
            for obj, path in self.iter_objects(lazy=True, return_path=True):
                try:
                    assert_sub_schema_is_lazy_loaded(obj)
                # intercept exceptions and add more information
                except BaseException as exc:
                    raise

    def test_create_group_across_segment(self):
        """
        Read {io_name} files in 'files_to_test' with
        create_group_across_segment test cases.

        Test read_block method of BaseFromRaw with different test cases
        for create_group_across_segment.

        """.format(io_name=self.ioclass.__name__)

        test_cases = [
            {"SpikeTrain": True},
            {"AnalogSignal": True},
            {"Event": True},
            {"Epoch": True},
            {"SpikeTrain": True,
             "AnalogSignal": True,
             "Event": True,
             "Epoch": True},
            True
        ]
        expected_outcomes = [
            None,
            None,
            NotImplementedError,
            NotImplementedError,
            NotImplementedError,
            NotImplementedError,
        ]

        mock_test_case = unittest.TestCase()
        if issubclass(self.ioclass, BaseFromRaw):
            for obj, reader in self.iter_objects(target=Block,
                                                 lazy=self.ioclass.support_lazy,
                                                 return_reader=True):
                if "create_group_across_segment" in inspect.signature(reader).parameters.keys():
                    # Ignore testing readers for IOs where read_block is overridden to exclude
                    # the create_group_across_segment functionality, for eg. NixIO_fr
                    for case, outcome in zip(test_cases, expected_outcomes):
                        if outcome is not None:
                            with mock_test_case.assertRaises(outcome):
                                reader(lazy=self.ioclass.support_lazy, create_group_across_segment=case)
                        else:
                            reader(lazy=self.ioclass.support_lazy, create_group_across_segment=case)

    def test__handle_pathlib_filename(self):
        if self.files_to_test:
            filename = get_test_file_full_path(self.ioclass, filename=self.files_to_test[0],
                                               directory=self.local_test_dir)
            pathlib_filename = pathlib.Path(filename)

            if self.ioclass.mode == 'file':
                self.ioclass(filename=pathlib_filename,
                             *self.default_arguments,
                             **self.default_keyword_arguments)
            elif self.ioclass.mode == 'dir':
                self.ioclass(dirname=pathlib_filename,
                             *self.default_arguments,
                             **self.default_keyword_arguments)

    def test_list_candidate_ios(self):
        for entity in self.entities_to_test:
            entity = get_test_file_full_path(self.ioclass, filename=entity,
                                             directory=self.local_test_dir)
            ios = list_candidate_ios(entity)
            assert self.ioclass in ios