#!/usr/bin/env python
#
# Copyright (c), 2022, SISSA (International School for Advanced Studies).
# All rights reserved.
# This file is distributed under the terms of the MIT License.
# See the file 'LICENSE' in the root directory of the present
# distribution, or http://opensource.org/licenses/MIT.
#
# @author Davide Brunato <brunato@sissa.it>
#
import unittest
import io
from textwrap import dedent
from xml.etree import ElementTree

try:
    import xmlschema
except ImportError:
    xmlschema = None

from elementpath.sequence_types import normalize_sequence_type, is_instance, \
    is_sequence_type, match_sequence_type, is_sequence_type_restriction
from elementpath import XPath2Parser, XPathContext
from elementpath.xpath3 import XPath30Parser, XPath31Parser
from elementpath.namespaces import XSD_NAMESPACE, XSD_UNTYPED_ATOMIC, \
    XSD_ANY_ATOMIC_TYPE, XSD_ANY_SIMPLE_TYPE, XSI_NIL, XSD_STRING
from elementpath.datatypes import UntypedAtomic
from elementpath.xpath_nodes import CommentNode


class SequenceTypesTest(unittest.TestCase):

    def test_normalize_sequence_type_function(self):
        self.assertEqual(normalize_sequence_type(' xs:integer + '), 'xs:integer+')
        self.assertEqual(normalize_sequence_type(' xs :integer + '), 'xs :integer+')  # Invalid
        self.assertEqual(normalize_sequence_type(' element( * ) '), 'element(*)')
        self.assertEqual(normalize_sequence_type(' element( *,xs:int ) '), 'element(*, xs:int)')
        self.assertEqual(normalize_sequence_type(' \nfunction  ( * )\t '), 'function(*)')
        self.assertEqual(
            normalize_sequence_type(' \nfunction  ( item( ) * ) as  xs:integer\t '),
            'function(item()*) as xs:integer'
        )

    def test_is_sequence_type_restriction_function(self):
        self.assertTrue(is_sequence_type_restriction('xs:error?', 'none'))
        self.assertTrue(is_sequence_type_restriction('empty-sequence()', 'none'))
        self.assertTrue(is_sequence_type_restriction('xs:error*', 'empty-sequence()'))

        self.assertFalse(is_sequence_type_restriction('xs:integer', 'item()*'))
        self.assertFalse(is_sequence_type_restriction('xs:integer', 'item()?'))
        self.assertFalse(is_sequence_type_restriction('xs:integer', 'item()'))

        self.assertFalse(is_sequence_type_restriction('xs:integer+', 'xs:integer*'))
        self.assertFalse(is_sequence_type_restriction('xs:integer+', 'xs:integer?'))
        self.assertTrue(is_sequence_type_restriction('xs:integer+', 'xs:integer+'))
        self.assertTrue(is_sequence_type_restriction('xs:integer+', 'xs:integer'))

        self.assertFalse(is_sequence_type_restriction('xs:integer*', 'xs:integer?'))
        self.assertFalse(is_sequence_type_restriction('xs:integer*', 'xs:integer+'))
        self.assertTrue(is_sequence_type_restriction('xs:integer*', 'xs:integer*'))
        self.assertTrue(is_sequence_type_restriction('xs:integer*', 'xs:integer'))

        self.assertFalse(is_sequence_type_restriction('xs:integer?', 'xs:integer*'))
        self.assertFalse(is_sequence_type_restriction('xs:integer?', 'xs:integer+'))
        self.assertTrue(is_sequence_type_restriction('xs:integer?', 'xs:integer?'))
        self.assertTrue(is_sequence_type_restriction('xs:integer?', 'xs:integer'))

        self.assertTrue(is_sequence_type_restriction('node()', 'element()'))
        self.assertFalse(is_sequence_type_restriction('element()', 'node()'))
        self.assertTrue(is_sequence_type_restriction('xs:anyAtomicType', 'xs:string'))
        self.assertFalse(is_sequence_type_restriction('xs:anyAtomicType', 'xs:unknown'))
        self.assertTrue(is_sequence_type_restriction('xs:string', 'xs:anyAtomicType'))
        self.assertTrue(is_sequence_type_restriction('xs:string', 'xs:token'))
        self.assertFalse(is_sequence_type_restriction('xs:string', 'xs:int'))
        self.assertFalse(is_sequence_type_restriction('xs:string', 'xs:unknown'))
        self.assertFalse(is_sequence_type_restriction('element()', 'xs:string'))
        self.assertFalse(is_sequence_type_restriction('function(*)', 'xs:string'))
        self.assertFalse(is_sequence_type_restriction(
            'function(item()+) as xs:boolean', 'function(item()*) as xs:boolean'
        ))
        self.assertTrue(is_sequence_type_restriction(
            'function(item()) as xs:boolean', 'function(item()*) as xs:boolean'
        ))
        self.assertFalse(is_sequence_type_restriction(
            'function(item()+) as xs:boolean', 'function(item()) as xs:boolean'
        ))
        self.assertFalse(is_sequence_type_restriction(
            'function(item()) as xs:boolean', 'function(item()) as xs:string'
        ))
        self.assertFalse(is_sequence_type_restriction(
            'function(item(), item()) as xs:boolean', 'function(item()) as xs:boolean'
        ))

    def test_is_instance_function(self):
        self.assertTrue(is_instance(UntypedAtomic(1), XSD_UNTYPED_ATOMIC))
        self.assertFalse(is_instance(1, XSD_UNTYPED_ATOMIC))
        self.assertTrue(is_instance(1, XSD_ANY_ATOMIC_TYPE))
        self.assertFalse(is_instance([1], XSD_ANY_ATOMIC_TYPE))
        self.assertTrue(is_instance(1, XSD_ANY_SIMPLE_TYPE))
        self.assertTrue(is_instance([1], XSD_ANY_SIMPLE_TYPE))

        self.assertTrue(is_instance('foo', '{%s}string' % XSD_NAMESPACE))
        self.assertFalse(is_instance(1, '{%s}string' % XSD_NAMESPACE))
        self.assertTrue(is_instance(1.0, '{%s}double' % XSD_NAMESPACE))
        self.assertFalse(is_instance(1.0, '{%s}float' % XSD_NAMESPACE))

        parser = XPath2Parser(xsd_version='1.1')
        self.assertTrue(is_instance(1.0, '{%s}double' % XSD_NAMESPACE), parser)
        self.assertFalse(is_instance(1.0, '{%s}float' % XSD_NAMESPACE), parser)

        self.assertRaises(KeyError, is_instance, 'foo', '{%s}unknown' % XSD_NAMESPACE)
        self.assertRaises(KeyError, is_instance, 'foo', '{%s}unknown' % XSD_NAMESPACE, parser)

        self.assertRaises(KeyError, is_instance, 'foo', 'tst:unknown')
        self.assertRaises(KeyError, is_instance, 'foo', 'tst:unknown', parser)

        self.assertTrue(is_instance(None, '{%s}error' % XSD_NAMESPACE))
        self.assertTrue(is_instance([], '{%s}error' % XSD_NAMESPACE))
        self.assertFalse(is_instance(1.0, '{%s}error' % XSD_NAMESPACE))

        self.assertTrue(is_instance(1.0, '{%s}numeric' % XSD_NAMESPACE))
        self.assertFalse(is_instance(True, '{%s}numeric' % XSD_NAMESPACE))
        self.assertFalse(is_instance('foo', '{%s}numeric' % XSD_NAMESPACE))

    def test_is_sequence_type_function(self):
        self.assertTrue(is_sequence_type('empty-sequence()'))
        self.assertTrue(is_sequence_type('xs:string'))
        self.assertTrue(is_sequence_type('xs:float+'))
        self.assertTrue(is_sequence_type('element()*'))
        self.assertTrue(is_sequence_type('item()?'))
        self.assertTrue(is_sequence_type('xs:untypedAtomic+'))

        self.assertFalse(is_sequence_type(10))
        self.assertFalse(is_sequence_type(''))
        self.assertFalse(is_sequence_type('empty-sequence()*'))
        self.assertFalse(is_sequence_type('unknown'))
        self.assertFalse(is_sequence_type('unknown?'))
        self.assertFalse(is_sequence_type('tns0:unknown'))

        self.assertTrue(is_sequence_type(' element( ) '))
        self.assertTrue(is_sequence_type(' element( * ) '))
        self.assertFalse(is_sequence_type(' element( *, * ) '))
        self.assertTrue(is_sequence_type('element(A)'))
        self.assertTrue(is_sequence_type('element(A, xs:date)'))
        self.assertTrue(is_sequence_type('element(*, xs:date)'))
        self.assertFalse(is_sequence_type('element(A, B, xs:date)'))

        self.assertTrue(is_sequence_type('document-node(element(*, xs:date))'))
        self.assertFalse(is_sequence_type('document-node(element(*, xs:date)'))
        self.assertFalse(is_sequence_type('document-node(xs:date)'))

        parser = XPath2Parser()
        self.assertFalse(is_sequence_type('function(*)', parser))
        self.assertFalse(is_sequence_type('function(xs:string)', parser))
        self.assertFalse(is_sequence_type('map(xs:string, xs:string)', parser))
        self.assertFalse(is_sequence_type('array(xs:string)', parser))

        parser = XPath30Parser()
        self.assertTrue(is_sequence_type('function(*)', parser))
        self.assertTrue(is_sequence_type('function(xs:string)', parser))
        self.assertFalse(is_sequence_type('function(xs:string', parser))
        self.assertFalse(is_sequence_type('map(xs:string, xs:string)', parser))
        self.assertFalse(is_sequence_type('array(xs:string)', parser))

        parser = XPath31Parser()
        self.assertTrue(is_sequence_type('function(*)', parser))
        self.assertTrue(is_sequence_type('map(xs:string, xs:string)', parser))
        self.assertFalse(is_sequence_type('map(xs:string, xs:string', parser))
        self.assertTrue(is_sequence_type('array(xs:string)', parser))

        # Without a parser argument assumes the latest version coverage
        self.assertTrue(is_sequence_type('function(*)'))
        self.assertTrue(is_sequence_type('map(xs:string, xs:string)'))
        self.assertFalse(is_sequence_type('map(xs:string, xs:string'))
        self.assertTrue(is_sequence_type('array(xs:string)'))

        self.assertTrue(is_sequence_type('function(xs:int) as xs:int'))
        self.assertFalse(is_sequence_type('function(xs:unknown) as xs:int'))
        self.assertFalse(is_sequence_type('function(xs:int) as xs:unknown'))
        self.assertTrue(is_sequence_type('function(xs:int, ...) as xs:int'))

        self.assertTrue(is_sequence_type('function(xs:int, function(*)) as xs:int'))
        self.assertTrue(is_sequence_type('function(function(*), xs:int) as xs:int'))

        self.assertTrue(
            is_sequence_type('function(xs:int, function(xs:int) as xs:int) as xs:int')
        )
        self.assertFalse(
            is_sequence_type('function(function(xs:int) as xs:int, xs:int) as xs:int')
        )

    def test_match_sequence_type_function(self):
        self.assertTrue(match_sequence_type(None, 'empty-sequence()'))
        self.assertTrue(match_sequence_type([], 'empty-sequence()'))
        self.assertFalse(match_sequence_type('', 'empty-sequence()'))

        self.assertFalse(match_sequence_type('', 'empty-sequence()'))

        context = XPathContext(ElementTree.XML('<root><e1>1</e1><e2/><e3/></root>'))
        root = context.root

        self.assertTrue(match_sequence_type(root, 'element()'))
        self.assertTrue(match_sequence_type(root, 'element(root)'))
        self.assertFalse(match_sequence_type(root, 'element(foo)'))

        self.assertTrue(match_sequence_type(root, 'element(root, xs:untyped)'))
        self.assertTrue(match_sequence_type(root, 'element(root, xs:untyped?)'))

        if xmlschema is not None:
            schema = xmlschema.XMLSchema(dedent('''\
                <xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema">
                  <xs:element name="root" type="xs:string"/>
                </xs:schema>'''))

            root.xsd_type = schema.maps.types[XSD_STRING]
            self.assertFalse(match_sequence_type(root, 'element(root, xs:untyped)'))
            root.xsd_type = None

        root.obj.attrib[XSI_NIL] = 'true'
        self.assertFalse(match_sequence_type(root, 'element(root, xs:untyped)'))
        self.assertTrue(match_sequence_type(root, 'element(root, xs:untyped?)'))
        root.elem.attrib.pop(XSI_NIL)

        self.assertFalse(match_sequence_type(root, 'element(root, xs:string)'))
        self.assertFalse(match_sequence_type(root, 'element(root/e1, xs:string)'))
        self.assertTrue(match_sequence_type(root, 'element(root, xs:untypedAtomic)'))
        self.assertFalse(match_sequence_type(root, 'element(xs:root, xs:untypedAtomic)'))

        with self.assertRaises(NameError):
            match_sequence_type(root, 'element(root, xs:unknown)')

        parser = XPath2Parser()
        self.assertFalse(match_sequence_type(root, 'element(xs:root)', parser))
        self.assertFalse(match_sequence_type(root, 'element(tns:root)', parser))

        self.assertFalse(match_sequence_type(1.0, 'element()'))
        self.assertTrue(match_sequence_type([root], 'element()'))
        self.assertTrue(match_sequence_type(root, 'element()?'))
        self.assertTrue(match_sequence_type(root, 'element()+'))
        self.assertTrue(match_sequence_type(root, 'element()*'))
        self.assertFalse(match_sequence_type(root[:], 'element()'))
        self.assertFalse(match_sequence_type(root[:], 'element()?'))
        self.assertTrue(match_sequence_type(root[:], 'element()+'))
        self.assertTrue(match_sequence_type(root[:], 'element()*'))

        self.assertTrue(match_sequence_type(root, 'element(*)'))

        document = ElementTree.parse(io.StringIO('<root/>'))
        context = XPathContext(document)
        root = context.root

        self.assertTrue(match_sequence_type(root, 'document-node(element())'))
        self.assertFalse(match_sequence_type(root, 'document-node(element(A))'))

        parser = XPath2Parser()
        self.assertTrue(match_sequence_type(UntypedAtomic(1), 'xs:untypedAtomic'))
        self.assertFalse(match_sequence_type(1, 'xs:untypedAtomic'))

        self.assertTrue(match_sequence_type('1', 'xs:string'))
        self.assertFalse(match_sequence_type(1, 'xs:string'))

        with self.assertRaises(NameError) as ctx:
            match_sequence_type('1', 'xs:unknown', parser)
        self.assertIn('XPST0051', str(ctx.exception))

        with self.assertRaises(NameError) as ctx:
            match_sequence_type('1', 'tns0:string', parser)
        self.assertIn('XPST0051', str(ctx.exception))

        token = parser.parse('true()')
        self.assertFalse(match_sequence_type(1.0, 'function(*)'))
        self.assertTrue(match_sequence_type(token, 'function(*)'))
        self.assertTrue(match_sequence_type(token, 'function() as xs:boolean'))
        self.assertFalse(match_sequence_type(token, 'function() as xs:int'))

        parser = XPath31Parser()
        self.assertFalse(match_sequence_type(1.0, 'array(*)'))
        self.assertFalse(match_sequence_type(1.0, 'map(*)'))

        token = parser.parse('[1, 2, 3]')
        self.assertTrue(match_sequence_type(token, 'array(*)'))
        self.assertTrue(match_sequence_type(token, 'array(xs:integer)'))
        self.assertFalse(match_sequence_type(token, 'array(xs:string)'))
        self.assertFalse(match_sequence_type(token, 'map(*)'))

        token = parser.parse('map{1: 2}')
        self.assertFalse(match_sequence_type(token, 'array(*)'))
        self.assertTrue(match_sequence_type(token, 'map(*)'))
        self.assertTrue(match_sequence_type(token, 'map(xs:integer, xs:integer)'))
        self.assertFalse(match_sequence_type(token, 'map(xs:string, xs:integer)'))

        with self.assertRaises(SyntaxError):
            match_sequence_type(token, 'map(xs:integer+, xs:integer)')

        self.assertFalse(match_sequence_type('foo', 'xs:anyURI'))
        self.assertTrue(match_sequence_type('foo', 'xs:anyURI', strict=False))

        comment = ElementTree.Comment('foo')
        comment_node = CommentNode(comment)
        self.assertTrue(match_sequence_type(comment_node, 'comment()'))
        self.assertFalse(match_sequence_type(comment_node, 'comment(*)'))


if __name__ == '__main__':
    unittest.main()
