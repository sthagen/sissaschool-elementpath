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
#
# Note: Many tests are built using the examples of the XPath standards,
#       published by W3C under the W3C Document License.
#
#       References:
#           http://www.w3.org/TR/1999/REC-xpath-19991116/
#           http://www.w3.org/TR/2010/REC-xpath20-20101214/
#           http://www.w3.org/TR/2010/REC-xpath-functions-20101214/
#           https://www.w3.org/Consortium/Legal/2015/doc-license
#           https://www.w3.org/TR/charmod-norm/
#
import unittest
import math
from copy import copy
from contextlib import contextmanager
from xml.etree import ElementTree

from elementpath import ElementPathError, XPath2Parser, XPathContext, \
    XPathFunction, select
from elementpath.namespaces import XML_NAMESPACE, XSD_NAMESPACE, \
    XSI_NAMESPACE, XPATH_FUNCTIONS_NAMESPACE


class DummyXsdType:
    name = local_name = None

    @property
    def root_type(self): return self
    @property
    def simple_type(self): return self
    def is_matching(self, name, default_namespace): pass
    def is_empty(self): pass
    def is_simple(self): pass
    def has_simple_content(self): pass
    def has_mixed_content(self): pass
    def is_element_only(self): pass
    def is_key(self): pass
    def is_qname(self): pass
    def is_notation(self): pass
    def decode(self, obj, *args, **kwargs): pass
    def validate(self, obj, *args, **kwargs): pass


# noinspection PyPropertyAccess
class XPathTestCase(unittest.TestCase):
    namespaces = {
        'xml': XML_NAMESPACE,
        'xs': XSD_NAMESPACE,
        'xsi': XSI_NAMESPACE,
        'fn': XPATH_FUNCTIONS_NAMESPACE,
        'eg': 'http://www.example.com/ns/',
        'tst': 'http://xpath.test/ns',
    }
    variables = {
        'values': [10, 20, 5],
        'myaddress': 'admin@example.com',
        'word': 'alpha',
    }
    etree = ElementTree

    def setUp(self):
        self.parser = XPath2Parser(self.namespaces)

    #
    # Helper methods
    def check_tokenizer(self, path, expected):
        """
        Checks the list of lexemes generated by the parser tokenizer.

        :param path: the XPath expression to be checked.
        :param expected: a list with lexemes generated by the tokenizer.
        """
        self.assertEqual([
            lit or symbol or name or unexpected
            for lit, symbol, name, unexpected in self.parser.__class__.tokenizer.findall(path)
        ], expected)

    def check_token(self, symbol, expected_label=None, expected_str=None,
                    expected_repr=None, value=None):
        """
        Checks a token class of an XPath parser class. The instance of the token is created
        using the value argument and than is checked against other optional arguments.

        :param symbol: the string that identifies the token class in the parser's symbol table.
        :param expected_label: the expected label for the token instance.
        :param expected_str: the expected string conversion of the token instance.
        :param expected_repr: the expected string representation of the token instance.
        :param value: the value used to create the token instance.
        """
        token = self.parser.symbol_table[symbol](self.parser, value)
        self.assertEqual(token.symbol, symbol)
        if expected_label is not None:
            self.assertEqual(token.label, expected_label)
        if expected_str is not None:
            self.assertEqual(str(token), expected_str)
        if expected_repr is not None:
            self.assertEqual(repr(token), expected_repr)

    def check_tree(self, path, expected):
        """
        Checks the tree string representation of a parsed path.

        :param path: an XPath expression.
        :param expected: the expected result string.
        """
        token = self.parser.parse(path)
        self.assertEqual(token.tree, expected)

    def check_source(self, path, expected=None):
        """
        Checks the source representation of a parsed path.

        :param path: an XPath expression.
        :param expected: the expected result string.
        """
        token = self.parser.parse(path)
        self.assertEqual(token.source, expected or path)

    def check_value(self, path, expected=None, context=None):
        """
        Checks the result of the *evaluate* method with an XPath expression. The evaluation
        is applied on the root token of the parsed XPath expression.

        :param path: an XPath expression.
        :param expected: the expected result. Can be a data instance to compare to the result, \
        a type to be used to check the type of the result, a function that accepts the result \
        as argument and returns a boolean value, an exception class that is raised by running \
        the evaluate method.
        :param context: an optional `XPathContext` instance to be passed to evaluate method.
        """
        context = copy(context)
        try:
            root_token = self.parser.parse(path)
        except ElementPathError as err:
            if isinstance(expected, type) and isinstance(err, expected):
                return
            raise

        if expected is None:
            self.assertEqual(root_token.evaluate(context), [])
        elif isinstance(expected, type):
            if issubclass(expected, Exception):
                self.assertRaises(expected, root_token.evaluate, context)
            else:
                self.assertIsInstance(root_token.evaluate(context), expected)

        elif isinstance(expected, float):
            value = root_token.evaluate(context)
            if not math.isnan(expected):
                self.assertAlmostEqual(value, expected)
            else:
                if isinstance(value, list):
                    value = [x for x in value if value is not None and value != []]
                    self.assertTrue(len(value) == 1)
                    value = value[0]

                self.assertIsInstance(value, float)
                self.assertTrue(math.isnan(value))

        elif isinstance(expected, list):
            self.assertListEqual(root_token.evaluate(context), expected)
        elif isinstance(expected, set):
            self.assertEqual(set(root_token.evaluate(context)), expected)
        elif isinstance(expected, XPathFunction) or not callable(expected):
            self.assertEqual(root_token.evaluate(context), expected)
        else:
            self.assertTrue(expected(root_token.evaluate(context)))

    def check_select(self, path, expected, context=None):
        """
        Checks the materialized result of the *select* method with an XPath expression.
        The selection is applied on the root token of the parsed XPath expression.

        :param path: an XPath expression.
        :param expected: the expected result. Can be a data instance to compare to the result, \
        a function that accepts the result as argument and returns a boolean value, an exception \
        class that is raised by running the evaluate method.
        :param context: an optional `XPathContext` instance to be passed to evaluate method. If no \
        context is provided the method is called with a dummy context.
        """
        if context is None:
            context = XPathContext(root=self.etree.Element(u'dummy_root'))
        else:
            context = copy(context)

        root_token = self.parser.parse(path)
        if isinstance(expected, type) and issubclass(expected, Exception):
            self.assertRaises(expected, root_token.select, context)
        elif isinstance(expected, list):
            self.assertListEqual(list(root_token.select(context)), expected)
        elif isinstance(expected, set):
            self.assertEqual(set(root_token.select(context)), expected)
        elif callable(expected):
            self.assertTrue(expected(list(root_token.parser.parse(path).select(context))))
        else:
            self.assertEqual(list(root_token.select(context)), expected)  # must fail

    def check_selector(self, path, root, expected, namespaces=None, **kwargs):
        """
        Checks using the selector API, namely the *select* function at package level.

        :param path: an XPath expression.
        :param root: an Element or an ElementTree instance.
        :param expected: the expected result. Can be a data instance to compare to the result, \
        a type to be used to check the type of the result, a function that accepts the result \
        as argument and returns a boolean value, an exception class that is raised by running \
        the evaluate method.
        :param namespaces: an optional mapping from prefixes to namespace URIs.
        :param kwargs: other optional arguments for the parser class.
        """
        if isinstance(expected, type) and issubclass(expected, Exception):
            self.assertRaises(expected, select, root, path, namespaces,
                              self.parser.__class__, **kwargs)
        else:
            results = select(root, path, namespaces, self.parser.__class__, **kwargs)
            if isinstance(expected, list):
                self.assertListEqual(results, expected)
            elif isinstance(expected, set):
                self.assertEqual(set(results), expected)
            elif isinstance(expected, float):
                if math.isnan(expected):
                    self.assertTrue(math.isnan(results))
                else:
                    self.assertAlmostEqual(results, expected)
            elif not callable(expected):
                self.assertEqual(results, expected)
            elif isinstance(expected, type):
                self.assertIsInstance(results, expected)
            else:
                self.assertTrue(expected(results))

    @contextmanager
    def schema_bound_parser(self, schema_proxy):
        # Code to acquire resource, e.g.:
        self.parser.schema = schema_proxy
        try:
            yield self.parser
        finally:
            self.parser.schema = None

    @contextmanager
    def xsd_version_parser(self, xsd_version):
        xsd_version, self.parser._xsd_version = self.parser._xsd_version, xsd_version
        try:
            yield self.parser
        finally:
            self.parser._xsd_version = xsd_version

    # Wrong XPath expression checker shortcuts
    def check_raise(self, path, exception_class, *message_parts, context=None):
        with self.assertRaises(exception_class) as error_context:
            root_token = self.parser.parse(path)
            root_token.evaluate(copy(context))

        for part in message_parts:
            self.assertIn(part, str(error_context.exception))

    def wrong_syntax(self, path, *message_parts, context=None):
        with self.assertRaises(SyntaxError) as error_context:
            root_token = self.parser.parse(path)
            root_token.evaluate(copy(context))

        for part in message_parts:
            self.assertIn(part, str(error_context.exception))

    def wrong_value(self, path, *message_parts, context=None):
        with self.assertRaises(ValueError) as error_context:
            root_token = self.parser.parse(path)
            root_token.evaluate(copy(context))

        for part in message_parts:
            self.assertIn(part, str(error_context.exception))

    def wrong_type(self, path, *message_parts, context=None):
        with self.assertRaises(TypeError) as error_context:
            root_token = self.parser.parse(path)
            root_token.evaluate(copy(context))

        for part in message_parts:
            self.assertIn(part, str(error_context.exception))

    def wrong_name(self, path, *message_parts, context=None):
        with self.assertRaises(NameError) as error_context:
            root_token = self.parser.parse(path)
            root_token.evaluate(copy(context))

        for part in message_parts:
            self.assertIn(part, str(error_context.exception))


if __name__ == '__main__':
    unittest.main()
