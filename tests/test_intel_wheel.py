"""An Intel wheel must not need build-machine libraries or a newer macOS."""
import unittest

from scripts.verify_intel_wheel import check_native_report


class IntelWheelTests(unittest.TestCase):
    def test_library_identity_is_not_an_external_dependency(self):
        check_native_report('x86_64',
                            'module.so:\n\t@rpath/module.so (compatibility version 0.0.0)\n'
                            '\t/usr/lib/libSystem.B.dylib (compatibility version 1.0.0)\n',
                            'minos 14.2\n', '@rpath/module.so')

    def test_static_intel_binary_with_supported_deployment_target_is_accepted(self):
        check_native_report('x86_64', 'module.so:\n\t/usr/lib/libSystem.B.dylib (compatibility version 1.0.0)\n',
                            'cmd LC_BUILD_VERSION\n platform MACOS\n minos 14.2\n sdk 26.3\n')

    def test_homebrew_or_relative_dylibs_are_rejected(self):
        for dependency in ('/usr/local/opt/openssl/lib/libcrypto.dylib', '@rpath/libssl.dylib',
                           '/opt/homebrew/lib/libcrypto.dylib'):
            with self.subTest(dependency=dependency), self.assertRaises(ValueError):
                check_native_report('x86_64', 'module.so:\n\t' + dependency + ' (compatibility version 1.0.0)',
                                    'cmd LC_BUILD_VERSION\n minos 14.2\n')

    def test_wrong_architecture_newer_or_missing_deployment_target_is_rejected(self):
        for architecture, build in [('arm64', 'minos 14.2'), ('x86_64', 'minos 15.0'), ('x86_64', '')]:
            with self.subTest(architecture=architecture, build=build), self.assertRaises(ValueError):
                check_native_report(architecture, 'module.so:\n\t/usr/lib/libSystem.B.dylib (compatibility version 1.0.0)', build)
