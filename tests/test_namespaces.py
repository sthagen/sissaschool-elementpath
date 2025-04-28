#!/usr/bin/env python
#
# Copyright (c), 2018-2020, SISSA (International School for Advanced Studies).
# All rights reserved.
# This file is distributed under the terms of the MIT License.
# See the file 'LICENSE' in the root directory of the present
# distribution, or http://opensource.org/licenses/MIT.
#
# @author Davide Brunato <brunato@sissa.it>
#
import unittest

from elementpath.namespaces import XSD_NAMESPACE, get_namespace, \
    get_prefixed_name, get_expanded_name, split_expanded_name, get_expanded_path


class NamespacesTest(unittest.TestCase):
    namespaces = {
        'xs': XSD_NAMESPACE,
        'tst': "http://xpath.test/ns"
    }

    # namespaces.py module
    def test_get_namespace_function(self):
        self.assertEqual(get_namespace('A'), '')
        self.assertEqual(get_namespace('{ns}foo'), 'ns')
        self.assertEqual(get_namespace('{}foo'), '')
        self.assertEqual(get_namespace('{A}B{C}'), 'A')

    def test_get_prefixed_name_function(self):
        self.assertEqual(get_prefixed_name('{ns}foo', {'bar': 'ns'}), 'bar:foo')
        self.assertEqual(get_prefixed_name('{ns}foo', {'': 'ns'}), 'foo')
        self.assertEqual(get_prefixed_name('Q{ns}foo', {'': 'ns'}), 'foo')
        self.assertEqual(get_prefixed_name('foo', {'': 'ns'}), 'foo')
        self.assertEqual(get_prefixed_name('', {'': 'ns'}), '')
        self.assertEqual(get_prefixed_name('{ns}foo', {}), '{ns}foo')
        self.assertEqual(get_prefixed_name('{ns}foo', {'bar': 'other'}), '{ns}foo')

        with self.assertRaises(ValueError):
            get_prefixed_name('{{ns}}foo', {'bar': 'ns'})

    def test_get_expanded_name_function(self):
        self.assertEqual(get_expanded_name('{ns}foo', {'bar': 'ns'}), '{ns}foo')
        self.assertEqual(get_expanded_name('Q{ns}foo', {'bar': 'ns'}), '{ns}foo')
        self.assertEqual(get_expanded_name('bar:foo', {'bar': 'ns'}), '{ns}foo')
        self.assertEqual(get_expanded_name('foo', {'': 'ns'}), '{ns}foo')
        self.assertEqual(get_expanded_name('foo', {None: 'ns'}), '{ns}foo')
        self.assertEqual(get_expanded_name('', {'': 'ns'}), '')

        with self.assertRaises(KeyError):
            get_expanded_name('bar:foo', self.namespaces)
        with self.assertRaises(ValueError):
            get_expanded_name('bar:foo:bar', {'bar': 'ns'})
        with self.assertRaises(ValueError):
            get_expanded_name(':foo', {'': 'ns'})
        with self.assertRaises(ValueError):
            get_expanded_name('foo:', {'': 'ns'})

    def test_get_expanded_path_function(self):
        self.assertEqual(get_expanded_path('{ns}foo', {'bar': 'ns'}), '{ns}foo')
        self.assertEqual(get_expanded_path('Q{ns}foo', {'bar': 'ns'}), '{ns}foo')
        self.assertEqual(get_expanded_path('bar:foo', {'bar': 'ns'}), '{ns}foo')
        self.assertEqual(get_expanded_path('foo', {'': 'ns'}), '{ns}foo')
        self.assertEqual(get_expanded_path('foo', {None: 'ns'}), '{ns}foo')
        self.assertEqual(get_expanded_path('', {'': 'ns'}), '')

        with self.assertRaises(KeyError):
            get_expanded_path('bar:foo', self.namespaces)
        with self.assertRaises(ValueError):
            get_expanded_path('bar:foo:bar', {'bar': 'ns'})
        with self.assertRaises(ValueError):
            get_expanded_path(':foo', {'': 'ns'})
        with self.assertRaises(ValueError):
            get_expanded_path('foo:', {'': 'ns'})

        self.assertEqual(
            get_expanded_path('/{ns}foo', {'bar': 'ns'}), '/{ns}foo'
        )
        self.assertEqual(
            get_expanded_path('/Q{ns}foo/bar:item/@a', {'bar': 'ns'}),
            '/{ns}foo/{ns}item/@a'
        )
        self.assertEqual(
            get_expanded_path('/bar:foo', {'bar': 'ns'}), '/{ns}foo'
        )
        nsmap = {'': 'tns1', 'ns0': 'tns2'}
        self.assertEqual(
            get_expanded_path('/ns0:foo/bar[1]', nsmap), '/{tns2}foo/{tns1}bar[1]'
        )
        self.assertEqual(
            get_expanded_path('ns0:foo/bar[1]', nsmap), '{tns2}foo/{tns1}bar[1]'
        )
        self.assertEqual(
            get_expanded_path('./ns0:foo/bar[1]', nsmap), './{tns2}foo/{tns1}bar[1]'
        )
        self.assertEqual(
            get_expanded_path('/{tns1}foo/bar[1]', nsmap), '/{tns1}foo/{tns1}bar[1]'
        )

    def test_split_expanded_name_function(self):
        self.assertEqual(split_expanded_name('{ns}foo'), ('ns', 'foo'))
        self.assertEqual(split_expanded_name('foo'), ('', 'foo'))

        with self.assertRaises(ValueError):
            split_expanded_name('tst:foo')

        with self.assertRaises(ValueError):
            split_expanded_name('{{ns}}foo')


if __name__ == '__main__':
    unittest.main()
