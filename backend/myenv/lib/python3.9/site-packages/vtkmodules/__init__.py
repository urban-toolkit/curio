r"""
Currently, this package is experimental and may change in the future.
"""
from __future__ import absolute_import
import sys


def _windows_dll_path():
    import os
    _vtk_python_path = './vtkmodules'
    _vtk_dll_path = 'bin'
    # Compute the DLL path based on the location of the file and traversing up
    # the installation prefix to append the DLL path.
    _vtk_dll_directory = os.path.dirname(os.path.abspath(__file__))
    # Loop while we have components to remove.
    while _vtk_python_path not in ('', '.', '/'):
        # Strip a directory away.
        _vtk_python_path = os.path.dirname(_vtk_python_path)
        _vtk_dll_directory = os.path.dirname(_vtk_dll_directory)
    _vtk_dll_directory = os.path.join(_vtk_dll_directory, _vtk_dll_path)
    if os.path.exists(_vtk_dll_directory):
        # We never remove this path; it is required for VTK to work and there's
        # no scope where we can easily remove the directory again.
        _ = os.add_dll_directory(_vtk_dll_directory)

    # Build tree support.
    try:
        from . import _build_paths

        # Add any paths needed for the build tree.
        for path in _build_paths.paths:
            if os.path.exists(path):
                _ = os.add_dll_directory(path)
    except ImportError:
        # Relocatable install tree (or non-Windows).
        pass


# CPython 3.8 added behaviors which modified the DLL search path on Windows to
# only search "blessed" paths. When importing SMTK, ensure that SMTK's DLLs are
# in this set of "blessed" paths.
if sys.version_info >= (3, 8) and sys.platform == 'win32':
    _windows_dll_path()


#------------------------------------------------------------------------------
# this little trick is for static builds of VTK. In such builds, if
# the user imports this Python package in a non-statically linked Python
# interpreter i.e. not of the of the VTK-python executables, then we import the
# static components importer module.
def _load_vtkmodules_static():
    if 'vtkmodules_vtkCommonCore' not in sys.builtin_module_names:
        import _vtkmodules_static

#_load_vtkmodules_static()


#------------------------------------------------------------------------------
# list the contents
__all__ = [
    'vtkCommonCore',
    'vtkWebCore',
    'vtkCommonMath',
    'vtkCommonTransforms',
    'vtkCommonDataModel',
    'vtkCommonExecutionModel',
    'vtkIOCore',
    'vtkImagingCore',
    'vtkIOImage',
    'vtkIOXMLParser',
    'vtkIOXML',
    'vtkCommonMisc',
    'vtkFiltersCore',
    'vtkRenderingCore',
    'vtkRenderingContext2D',
    'vtkRenderingFreeType',
    'vtkRenderingSceneGraph',
    'vtkRenderingVtkJS',
    'vtkIOExport',
    'vtkWebGLExporter',
    'vtkCommonComputationalGeometry',
    'vtkCommonSystem',
    'vtkIOLegacy',
    'vtkDomainsChemistry',
    'vtkFiltersSources',
    'vtkFiltersGeneral',
    'vtkRenderingHyperTreeGrid',
    'vtkRenderingUI',
    'vtkRenderingOpenGL2',
    'vtkRenderingContextOpenGL2',
    'vtkRenderingVolume',
    'vtkImagingMath',
    'vtkRenderingVolumeOpenGL2',
    'vtkInteractionWidgets',
    'vtkViewsCore',
    'vtkViewsContext2D',
    'vtkTestingRendering',
    'vtkInteractionStyle',
    'vtkViewsInfovis',
    'vtkRenderingVolumeAMR',
    'vtkPythonContext2D',
    'vtkRenderingParallel',
    'vtkRenderingVR',
    'vtkRenderingMatplotlib',
    'vtkRenderingLabel',
    'vtkRenderingLOD',
    'vtkRenderingLICOpenGL2',
    'vtkRenderingImage',
    'vtkRenderingExternal',
    'vtkFiltersCellGrid',
    'vtkRenderingCellGrid',
    'vtkIOXdmf2',
    'vtkIOVeraOut',
    'vtkIOVPIC',
    'vtkIOTecplotTable',
    'vtkIOTRUCHAS',
    'vtkIOSegY',
    'vtkIOParallelXML',
    'vtkIOLSDyna',
    'vtkIOParallelLSDyna',
    'vtkIOExodus',
    'vtkIOParallelExodus',
    'vtkIOPLY',
    'vtkIOPIO',
    'vtkIOMovie',
    'vtkIOOggTheora',
    'vtkIOOMF',
    'vtkIONetCDF',
    'vtkIOMotionFX',
    'vtkIOGeometry',
    'vtkIOParallel',
    'vtkIOMINC',
    'vtkIOInfovis',
    'vtkIOImport',
    'vtkParallelCore',
    'vtkIOIOSS',
    'vtkIOH5part',
    'vtkIOH5Rage',
    'vtkIOGeoJSON',
    'vtkIOFLUENTCFF',
    'vtkIOVideo',
    'vtkIOExportPDF',
    'vtkRenderingGL2PSOpenGL2',
    'vtkIOExportGL2PS',
    'vtkIOEnSight',
    'vtkIOCityGML',
    'vtkIOChemistry',
    'vtkIOCesium3DTiles',
    'vtkIOCellGrid',
    'vtkIOCONVERGECFD',
    'vtkIOHDF',
    'vtkIOCGNSReader',
    'vtkIOAsynchronous',
    'vtkIOAMR',
    'vtkInteractionImage',
    'vtkImagingStencil',
    'vtkImagingStatistics',
    'vtkImagingGeneral',
    'vtkImagingOpenGL2',
    'vtkImagingMorphological',
    'vtkImagingFourier',
    'vtkIOSQL',
    'vtkCommonColor',
    'vtkImagingSources',
    'vtkInfovisCore',
    'vtkGeovisCore',
    'vtkInfovisLayout',
    'vtkRenderingAnnotation',
    'vtkImagingHybrid',
    'vtkImagingColor',
    'vtkFiltersTopology',
    'vtkFiltersTensor',
    'vtkFiltersSelection',
    'vtkFiltersSMP',
    'vtkFiltersReduction',
    'vtkFiltersPython',
    'vtkFiltersProgrammable',
    'vtkFiltersModeling',
    'vtkFiltersPoints',
    'vtkFiltersStatistics',
    'vtkFiltersParallelStatistics',
    'vtkFiltersImaging',
    'vtkFiltersExtraction',
    'vtkFiltersGeometry',
    'vtkFiltersHybrid',
    'vtkFiltersHyperTree',
    'vtkFiltersTexture',
    'vtkFiltersParallel',
    'vtkFiltersParallelImaging',
    'vtkFiltersParallelDIY2',
    'vtkFiltersGeometryPreview',
    'vtkFiltersGeneric',
    'vtkFiltersFlowPaths',
    'vtkFiltersAMR',
    'vtkDomainsChemistryOpenGL2',
    'vtkCommonPython',
    'vtkChartsCore',
    'vtkAcceleratorsVTKmCore',
    'vtkAcceleratorsVTKmDataModel',
    'vtkAcceleratorsVTKmFilters',
    'vtkFiltersVerdict',
    'all',
    'gtk',
    'numpy_interface',
    'qt',
    'test',
    'tk',
    'util',
    'wx',
]

#------------------------------------------------------------------------------
# get the version
__version__ = "9.3.1"
