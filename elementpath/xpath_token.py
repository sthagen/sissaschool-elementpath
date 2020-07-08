#
# Copyright (c), 2018-2020, SISSA (International School for Advanced Studies).
# All rights reserved.
# This file is distributed under the terms of the MIT License.
# See the file 'LICENSE' in the root directory of the present
# distribution, or http://opensource.org/licenses/MIT.
#
# @author Davide Brunato <brunato@sissa.it>
#
"""
XPathToken and helper functions for XPath nodes. XPath error messages and node helper functions
are embedded in XPathToken class, in order to raise errors related to token instances.

In XPath there are 7 kinds of nodes:

    element, attribute, text, namespace, processing-instruction, comment, document

Element-like objects are used for representing elements and comments, ElementTree-like objects
for documents. Generic tuples are used for representing attributes and named-tuples for namespaces.
"""
import locale
import contextlib
from decimal import Decimal
import urllib.parse

from .exceptions import ElementPathValueError, XPATH_ERROR_CODES
from .namespaces import XQT_ERRORS_NAMESPACE, XSD_NAMESPACE, XPATH_FUNCTIONS_NAMESPACE, \
    XSD_ANY_TYPE, XSD_ANY_SIMPLE_TYPE, XSD_ANY_ATOMIC_TYPE
from .xpath_nodes import AttributeNode, TextNode, TypedAttribute, TypedElement, \
    is_etree_element, is_attribute_node, etree_iter_strings, is_text_node, \
    is_namespace_node, is_comment_node, is_processing_instruction_node, \
    is_element_node, is_document_node, is_xpath_node, is_schema_node
from .datatypes import UntypedAtomic, Timezone, DateTime10, Date10, \
    DayTimeDuration, XSD_BUILTIN_TYPES
from .schema_proxy import AbstractSchemaProxy
from .tdop_parser import Token, MultiLabel
from .xpath_context import XPathSchemaContext


UNICODE_CODEPOINT_COLLATION = "http://www.w3.org/2005/xpath-functions/collation/codepoint"

XSD_SPECIAL_TYPES = {XSD_ANY_TYPE, XSD_ANY_SIMPLE_TYPE, XSD_ANY_ATOMIC_TYPE}


def ordinal(n):
    if n in {11, 12, 13}:
        return '%dth' % n

    least_significant_digit = n % 10
    if least_significant_digit == 1:
        return '%dst' % n
    elif least_significant_digit == 2:
        return '%dnd' % n
    elif least_significant_digit == 3:
        return '%drd' % n
    else:
        return '%dth' % n


class XPathToken(Token):
    """Base class for XPath tokens."""
    comment = None    # for XPath 2.0+ comments
    xsd_types = None   # fox XPath 2.0+ schema types labeling

    def evaluate(self, context=None):
        """
        Evaluate default method for XPath tokens.

        :param context: The XPath dynamic context.
        """
        return [x for x in self.select(context)]

    def select(self, context=None):
        """
        Select operator that generates XPath results.

        :param context: The XPath dynamic context.
        """
        item = self.evaluate(context)
        if item is not None:
            if isinstance(item, list):
                yield from item
            else:
                if context is not None:
                    context.item = item
                yield item

    def __str__(self):
        symbol, label = self.symbol, self.label
        if symbol == '$':
            return '$%s variable reference' % (self[0].value if self._items else '')
        elif symbol == ',':
            return 'comma operator' if self.parser.version > '1.0' else 'comma symbol'
        elif label in ('axis', 'function', 'sequence type', 'kind test', 'constructor'):
            return '%r %s' % (symbol, label)
        return super(XPathToken, self).__str__()

    @property
    def source(self):
        symbol, label = self.symbol, self.label
        if label == 'axis':
            return '%s::%s' % (self.symbol, self[0].source)
        elif label in ('function', 'sequence type', 'kind test', 'constructor'):
            return '%s(%s)' % (self.symbol, ', '.join(item.source for item in self))
        elif symbol == ':':
            return '%s:%s' % (self[0].source, self[1].source)
        elif symbol == '(':
            return '()' if not self else '(%s)' % self[0].source
        elif symbol == '[':
            return '%s[%s]' % (self[0].source, self[1].source)
        elif symbol == ',':
            return '%s, %s' % (self[0].source, self[1].source)
        elif symbol == '$':
            return '$%s' % self[0].source
        elif symbol == '{':
            return '{%s}%s' % (self[0].value, self[1].value)
        elif symbol == 'instance':
            return '%s instance of %s' % (self[0].source, ''.join(t.source for t in self[1:]))
        elif symbol == 'treat':
            return '%s treat as %s' % (self[0].source, ''.join(t.source for t in self[1:]))
        elif symbol == 'for':
            return 'for %s return %s' % (
                ', '.join('%s in %s' % (self[k].source, self[k + 1].source)
                          for k in range(0, len(self) - 1, 2)),
                self[-1].source
            )
        return super(XPathToken, self).source

    ###
    # Tokens tree analysis methods
    def iter_leaf_elements(self):
        """
        Iterates through the leaf elements of the token tree if there are any,
        returning QNames in prefixed format. A leaf element is an element
        positioned at last path step. Does not consider kind tests and wildcards.
        """
        if self.symbol in {'(name)', ':'}:
            yield self.value
        elif self.symbol in ('//', '/'):
            if self._items[-1].symbol in {
                '(name)', '*', ':', '..', '.', '[', 'self', 'child',
                'parent', 'following-sibling', 'preceding-sibling',
                'ancestor', 'ancestor-or-self', 'descendant',
                'descendant-or-self', 'following', 'preceding'
            }:
                yield from self._items[-1].iter_leaf_elements()

        elif self.symbol in ('[',):
            yield from self._items[0].iter_leaf_elements()
        else:
            for tk in self._items:
                yield from tk.iter_leaf_elements()

    ###
    # Dynamic context methods
    def get_argument(self, context, index=0, required=False, default_to_context=False,
                     default=None, cls=None):
        """
        Get the argument value of a function of constructor token. A zero length sequence is
        converted to a `None` value. If the function has no argument returns the context's
        item if the dynamic context is not `None`.

        :param context: the dynamic context.
        :param index: an index for select the argument to be got, the first for default.
        :param required: if set to `True` missing or empty sequence arguments are not allowed.
        :param default_to_context: if set to `True` then the item of the dynamic context is \
        returned when the argument is missing.
        :param default: the default value returned in case the argument is an empty sequence. \
        If not provided returns `None`.
        :param cls: if a type is provided performs a type checking on item.
        """
        try:
            selector = self._items[index].select
        except IndexError:
            if default_to_context:
                if context is None:
                    raise self.missing_context() from None
                item = context.item if context.item is not None else context.root
            elif required:
                msg = "missing %s argument" % ordinal(index + 1)
                raise self.error('XPST0017', msg) from None
            else:
                return
        else:
            item = None
            if context is not None:
                context = context.copy()

            for k, result in enumerate(selector(context)):
                if k == 0:
                    item = result
                elif not self.parser.compatibility_mode:
                    raise self.wrong_context_type(
                        "a sequence of more than one item is not allowed as argument"
                    )
                else:
                    break
            else:
                if item is None:
                    if not required:
                        return default
                    ord_arg = ordinal(index + 1)
                    msg = "A not empty sequence required for {} argument"
                    raise self.missing_sequence(msg.format(ord_arg))

        # Type promotion checking (see "function conversion rules" in XPath 2.0 language definition)
        if cls is not None and not isinstance(item, cls):
            if self.parser.compatibility_mode:
                if issubclass(cls, str):
                    return self.string_value(item)
                elif issubclass(cls, float) or issubclass(float, cls):
                    return self.number_value(item)

            if self.parser.version > '1.0':
                value = self.data_value(item)
                if isinstance(value, cls):
                    return value
                elif isinstance(value, UntypedAtomic):
                    try:
                        if issubclass(cls, str):
                            return str(value)
                        else:
                            return cls(value)
                    except (TypeError, ValueError):
                        pass

            message = "the %s argument %r is not an instance of %r"
            raise self.error('XPTY0004', message % (ordinal(index + 1), item, cls))

        return item

    def atomization(self, context=None):
        """
        Helper method for value atomization of a sequence.

        Ref: https://www.w3.org/TR/xpath20/#id-atomization

        :param context: the XPath context.
        """
        for item in self.select(context):
            value = self.data_value(item)
            if value is None:
                msg = "argument node {!r} does not have a typed value"
                raise self.error('FOTY0012', msg.format(item))
            else:
                yield value

    def get_atomized_operand(self, context=None):
        """
        Get the atomized value for an XPath operator.

        :param context: the XPath context.
        :return: the atomized value of a single length sequence or `None` if the sequence is empty.
        """
        selector = iter(self.atomization(context))
        try:
            value = next(selector)
        except StopIteration:
            return
        else:
            try:
                next(selector)
            except StopIteration:
                if isinstance(value, UntypedAtomic):
                    value = str(value)
                if isinstance(context, XPathSchemaContext):
                    return value
                if self.xsd_types and isinstance(value, str):
                    xsd_type = self.get_xsd_type(context.item)
                    if xsd_type is None:
                        pass
                    elif xsd_type.name in XSD_SPECIAL_TYPES:
                        value = UntypedAtomic(value)
                    else:
                        try:
                            value = xsd_type.decode(value)
                        except (TypeError, ValueError):
                            msg = "Type {!r} is not appropriate for the context"
                            raise self.wrong_context_type(msg.format(type(value)))
                return value
            else:
                msg = "atomized operand is a sequence of length greater than one"
                raise self.wrong_context_type(msg)

    def get_comparison_data(self, context):
        """
        Get comparison data couples for the general comparison of sequences. Different sequences
        maybe generated with an XPath 2.0 parser, depending on compatibility mode setting.

        Ref: https://www.w3.org/TR/xpath20/#id-general-comparisons

        :param context: the XPath dynamic context.
        :returns: a list of data couples.
        """
        if context is None:
            operand1 = [x for x in self._items[0].select()]
            operand2 = [x for x in self._items[1].select()]
        else:
            operand1 = [x for x in self._items[0].select(context.copy())]
            operand2 = [x for x in self._items[1].select(context.copy())]

        if self.parser.compatibility_mode:
            # Boolean comparison if one of the results is a single boolean value (1.)
            try:
                if isinstance(operand1[0], bool):
                    if len(operand1) == 1:
                        return [(operand1[0], self.boolean_value(operand2))]
                if isinstance(operand2[0], bool):
                    if len(operand2) == 1:
                        return [(self.boolean_value(operand1), operand2[0])]
            except IndexError:
                return []

            # Converts to float for lesser-greater operators (3.)
            if self.symbol in ('<', '<=', '>', '>='):
                return [
                    (float(self.data_value(value1)), float(self.data_value(value2)))
                    for value1 in operand1 for value2 in operand2
                ]

        return [(self.data_value(value1), self.data_value(value2))
                for value1 in operand1 for value2 in operand2]

    def select_results(self, context):
        """
        Generates formatted XPath results.

        :param context: the XPath dynamic context.
        """
        if self.parser.version != '1.0':
            self.parser.check_variables(context.variable_values)

        for result in self.select(context):
            if isinstance(result, (TypedElement, TextNode)):
                yield result[0]
            elif isinstance(result, AttributeNode):
                yield result[1]
            elif isinstance(result, TypedAttribute):
                yield result[0][1] if hasattr(result[0][1], 'type') else result[1]
            else:
                yield result

    def get_results(self, context):
        """
        Returns formatted XPath results.

        :param context: the XPath dynamic context.
        :return: a list or a simple datatype when the result is a single simple type \
        generated by a literal or function token.
        """
        if self.parser.version != '1.0':
            self.parser.check_variables(context.variable_values)

        results = [x for x in self.select_results(context)]
        if len(results) == 1:
            res = results[0]
            if isinstance(res, (bool, int, float, Decimal)):
                return res
            elif isinstance(res, tuple) or is_etree_element(res) or is_document_node(res):
                return results
            elif is_schema_node(res):
                return results
            elif self.symbol in ('text', 'node'):
                return results
            elif self.label in ('function', 'literal'):
                return res
            else:
                return results
        else:
            return results

    def get_operands(self, context, cls=None):
        """
        Returns the operands for a binary operator. Float arguments are converted
        to decimal if the other argument is a `Decimal` instance.

        :param context: the XPath dynamic context.
        :param cls: if a type is provided performs a type checking on item.
        :return: a couple of values representing the operands. If any operand \
        is not available returns a `(None, None)` couple.
        """
        arg1 = self.get_argument(context, cls=cls)
        if arg1 is None:
            return None, None

        arg2 = self.get_argument(context, index=1, cls=cls)
        if arg2 is None:
            return None, None

        if isinstance(arg1, Decimal) and isinstance(arg2, float):
            return arg1, Decimal(arg2)
        elif isinstance(arg2, Decimal) and isinstance(arg1, float):
            return Decimal(arg1), arg2

        return arg1, arg2

    def get_absolute_uri(self, uri):
        """
        Obtains an absolute URI from the argument and the static context.

        :param uri: a string representing an URI.
        :returns: the argument if it's an absolute URI. Otherwise returns the URI
        obtained by the join o the base_uri of the static context with the
        argument. Returns the argument if the base_uri is `None'.
        """
        url_parts = urllib.parse.urlparse(uri)
        if url_parts.scheme not in urllib.parse.uses_relative \
                or url_parts.path.startswith('/') \
                or self.parser.base_uri is None:
            return uri
        return urllib.parse.urljoin(self.parser.base_uri, uri)

    def get_namespace(self, prefix):
        """
        Resolves a prefix to a namespace raising an error (FONS0004) if the
        prefix is not found in the namespace map.
        """
        try:
            return self.parser.namespaces[prefix]
        except KeyError as err:
            msg = 'No namespace found for prefix %s' % str(err)
            raise self.error('FONS0004', msg) from None

    def bind_namespace(self, namespace):
        """
        Bind a token with a namespace. The token has to be a name, a name wildcard,
        a function or a constructor, otherwise a syntax error is raised. Functions
        and constructors must be limited to its namespaces.
        """
        if self.symbol not in ('(name)', '*') and self.label not in ('function', 'constructor'):
            raise self.wrong_syntax()
        elif namespace == XPATH_FUNCTIONS_NAMESPACE:
            if self.label != 'function':
                raise self.wrong_syntax(message="a function expected.")
            elif isinstance(self.label, MultiLabel):
                self.label = 'function'
        elif namespace == XSD_NAMESPACE:
            if self.symbol not in ('(name)', '*') and self.label != 'constructor':
                raise self.wrong_syntax(
                    message="an XSD element or a constructor function expected."
                )
            elif isinstance(self.label, MultiLabel):
                self.label = 'constructor'

    def adjust_datetime(self, context, cls):
        """
        XSD datetime adjust function helper.

        :param context: the XPath dynamic context.
        :param cls: the XSD datetime subclass to use.
        :return: an empty list if there is only one argument that is the empty sequence \
        or the adjusted XSD datetime instance.
        """
        if len(self) == 1:
            item = self.get_argument(context, cls=cls)
            if item is None:
                return
            timezone = getattr(context, 'timezone', None)
        else:
            item = self.get_argument(context=None, cls=cls)  # don't use implicit timezone
            timezone = self.get_argument(context, 1, cls=DayTimeDuration)
            if timezone is not None:
                try:
                    timezone = Timezone.fromduration(timezone)
                except ValueError as err:
                    raise self.error('FODT0003', str(err)) from None
            if item is None:
                return

        try:
            if item.tzinfo is not None and timezone is not None:
                if isinstance(item, DateTime10):
                    item += timezone.offset
                elif not isinstance(item, Date10):
                    item += timezone.offset - item.tzinfo.offset
                elif timezone.offset < item.tzinfo.offset:
                    item -= timezone.offset - item.tzinfo.offset
                    item -= DayTimeDuration.fromstring('P1D')
        except OverflowError as err:
            raise self.error('FOAR0002', str(err)) from None

        item.tzinfo = timezone
        return item

    @contextlib.contextmanager
    def use_locale(self, collation):
        """A context manager for use a locale setting for string comparison in a code block."""
        loc = locale.getlocale(locale.LC_COLLATE)
        if collation == UNICODE_CODEPOINT_COLLATION:
            collation = 'en_US.UTF-8'

        try:
            locale.setlocale(locale.LC_COLLATE, collation)
        except locale.Error:
            raise self.error('FOCH0002', 'Unsupported collation %r' % collation) from None
        else:
            yield
        finally:
            locale.setlocale(locale.LC_COLLATE, loc)

    ###
    # Schema context methods
    def add_xsd_type(self, name, xsd_type):
        """
        Adds an XSD type association to token.

        :param name: the name to match with the XSD type.
        :param xsd_type: the XSD type to add.
        """
        if self.xsd_types is None:
            self.xsd_types = {name: xsd_type}
        else:
            obj = self.xsd_types.get(name)
            if obj is None:
                self.xsd_types[name] = xsd_type
            elif not isinstance(obj, list):
                if obj is not xsd_type:
                    self.xsd_types[name] = [obj, xsd_type]
            elif xsd_type not in obj:
                obj.append(xsd_type)

        return xsd_type

    def match_xsd_type(self, schema_item, name):
        """
        Match a token with a schema type, checking the matching between the provided schema
        item and name. If there is a match and the token is already related with another
        schema type an exception is raised.

        :param schema_item: an XPath item related with a schema instance.
        :param name: a QName in extended format for matching the item.
        :returns: the matched XSD type or `None` if there isn't a match.
        """
        try:
            if isinstance(schema_item, AttributeNode):
                if not schema_item[1].is_matching(name):
                    return
                xsd_type = schema_item[1].type
            elif not schema_item.is_matching(name, self.parser.default_namespace):
                return
            else:
                xsd_type = schema_item.type
        except AttributeError:
            return

        self.add_xsd_type(name, xsd_type)

        try:
            value = XSD_BUILTIN_TYPES[xsd_type.local_name].value
        except KeyError:
            primitive_type = self.parser.schema.get_primitive_type(xsd_type)
            try:
                value = XSD_BUILTIN_TYPES[primitive_type.local_name].value
            except KeyError:
                value = UntypedAtomic('1')

        if isinstance(schema_item, AttributeNode):
            return TypedAttribute(schema_item, value)
        return TypedElement(schema_item, value)

    def get_xsd_type(self, item):
        """
        Returns the XSD type associated with an item. Match by item's name
        and XSD validity. Returns `None` if no XSD type is matching.

        :param item: a string or an AttributeNode or an element.
        """
        if not self.xsd_types or isinstance(self.xsd_types, AbstractSchemaProxy):
            return
        elif isinstance(item, str):
            xsd_type = self.xsd_types.get(item)
        elif isinstance(item, AttributeNode):
            xsd_type = self.xsd_types.get(item[0])
        else:
            xsd_type = self.xsd_types.get(item.tag)

        if not xsd_type:
            return
        elif not isinstance(xsd_type, list):
            return xsd_type
        elif isinstance(item, AttributeNode):
            for x in xsd_type:
                if x.is_valid(item[1]):
                    return x
        elif not isinstance(item, str):
            for x in xsd_type:
                if x.is_simple():
                    if x.is_valid(item.text):
                        return x
                elif x.is_valid(item):
                    return x

        return xsd_type[0]

    def get_typed_node(self, item):
        """
        Returns a typed node if the item is matching an XSD type.

        Ref:
          https://www.w3.org/TR/xpath20/#id-processing-model
          https://www.w3.org/TR/xpath20/#id-static-analysis
          https://www.w3.org/TR/xquery-semantics/

        :param item: an untyped attribute ot element.
        :return: a TypedAttribute or a TypedElement, or the argument \
        if it's not matching any associated XSD type.
        """
        xsd_type = self.get_xsd_type(item)
        if not xsd_type:
            return item

        try:
            if isinstance(item, AttributeNode):
                if xsd_type.name in XSD_SPECIAL_TYPES:
                    return TypedAttribute(item, UntypedAtomic(item[1]))
                else:
                    return TypedAttribute(item, xsd_type.decode(item[1]))

            elif xsd_type.is_simple() or xsd_type.has_simple_content():
                if xsd_type.name in XSD_SPECIAL_TYPES:
                    return TypedElement(item, UntypedAtomic(item.text))
                else:
                    return TypedElement(item, xsd_type.decode(item.text))
            else:
                return item

        except (TypeError, ValueError):
            msg = "Type {!r} does not match sequence type of {!r}"
            raise self.wrong_sequence_type(msg.format(xsd_type, item)) from None

    ###
    # XPath data accessors base functions
    def data_value(self, obj):
        """
        The typed value, as computed by fn:data() on each item.
        Returns an instance of UntypedAtomic for untyped data.

        https://www.w3.org/TR/xpath20/#dt-typed-value
        """
        if obj is None:
            return
        elif hasattr(obj, 'type'):
            return self.schema_node_value(obj)  # Schema context
        elif isinstance(obj, (TypedElement, TypedAttribute)):
            return obj[-1]
        elif is_namespace_node(obj):
            return obj[1]
        elif is_comment_node(obj):
            return obj.text
        elif is_processing_instruction_node(obj):
            return obj.text
        elif isinstance(obj, tuple):
            return UntypedAtomic(obj[-1])
        elif is_etree_element(obj):
            value = ''.join(etree_iter_strings(obj))
            return UntypedAtomic(value)
        elif is_document_node(obj):
            value = ''.join(etree_iter_strings(obj.getroot()))
            return UntypedAtomic(value)
        else:
            return obj

    def boolean_value(self, obj):
        """
        The effective boolean value, as computed by fn:boolean().
        """
        if isinstance(obj, list):
            if not obj:
                return False
            elif isinstance(obj[0], tuple):
                try:
                    value = obj[0][1]
                except IndexError:
                    value = obj[0][0]
                return True if isinstance(value, str) else bool(value)
            elif is_element_node(obj[0]):
                return True
            elif len(obj) == 1:
                return bool(obj[0])
            else:
                raise self.error(
                    code='FORG0006',
                    message="Effective boolean value is not defined for a sequence of two or "
                            "more items not starting with an XPath node.",
                ) from None
        elif isinstance(obj, tuple) or is_element_node(obj):
            msg = "Effective boolean value is not defined for {}."
            raise self.error('FORG0006', msg.format(obj))
        return bool(obj)

    def string_value(self, obj):
        """
        The string value, as computed by fn:string().
        """
        if obj is None:
            return ''
        elif is_schema_node(obj):
            return str(self.schema_node_value(obj))
        elif is_element_node(obj):
            return ''.join(etree_iter_strings(obj))
        elif is_attribute_node(obj):
            return str(obj[1])
        elif is_text_node(obj):
            return obj[0]
        elif is_document_node(obj):
            return ''.join(e.text for e in obj.getroot().iter() if e.text is not None)
        elif is_namespace_node(obj):
            return obj[1]
        elif is_comment_node(obj):
            return obj.text
        elif is_processing_instruction_node(obj):
            return obj.text
        elif isinstance(obj, bool):
            return 'true' if obj else 'false'
        else:
            return str(obj)

    def number_value(self, obj):
        """
        The numeric value, as computed by fn:number() on each item. Returns a float value.
        """
        try:
            return float(self.string_value(obj) if is_xpath_node(obj) else obj)
        except (TypeError, ValueError):
            return float('nan')

    def schema_node_value(self, obj):
        """
        Returns a sample typed value for the XSD schema node, valid in the value space
        of the node. Used for schema-based dynamic evaluation of XPath expressions.
        """
        try:
            try:
                return XSD_BUILTIN_TYPES[obj.type.local_name].value
            except KeyError:
                pass

            if obj.type.is_simple() or obj.type.has_simple_content():
                # In case of schema element or attribute use a the sample value
                # of the primitive type
                primitive_type = self.parser.schema.get_primitive_type(obj.type)
                try:
                    return XSD_BUILTIN_TYPES[primitive_type.local_name].value
                except KeyError:
                    return XSD_BUILTIN_TYPES['anyType'].value
            else:
                return UntypedAtomic('')

        except AttributeError:
            if self.parser.schema is None:
                raise self.missing_schema() from None
            msg = "the argument {!r} is not a node of an XSD schema".format(obj)
            raise self.wrong_type(msg) from None

    ###
    # Error handling helpers
    def error(self, code, message=None):
        """
        Returns an XPath error instance related with a code. An XPath/XQuery/XSLT error code is an
        alphanumeric token starting with four uppercase letters and ending with four digits.

        :param code: the error code.
        :param message: an optional custom additional message.
        """
        if ':' in code:
            try:
                prefix, code = code.split(':')
            except ValueError:
                raise ElementPathValueError(
                    message='%r is not a QName' % code,
                    code=self.parser.get_qname(XQT_ERRORS_NAMESPACE, 'XPTY0004'),
                    token=self,
                )
            else:
                if self.parser.namespaces.get(prefix) != XQT_ERRORS_NAMESPACE:
                    raise ElementPathValueError(
                        message='{} namespace required for code' % XQT_ERRORS_NAMESPACE,
                        code=self.parser.get_qname(XQT_ERRORS_NAMESPACE, 'XPTY0004'),
                        token=self,
                    )

        try:
            error_class, default_message = XPATH_ERROR_CODES[code]
        except KeyError:
            raise ElementPathValueError(
                message='unknown XPath error code %r' % code,
                code=self.parser.get_qname(XQT_ERRORS_NAMESPACE, 'XPTY0004'),
                token=self,
            )
        else:
            return error_class(
                message=message or default_message,
                code=self.parser.get_qname(XQT_ERRORS_NAMESPACE, code),
                token=self,
            )

    # Shortcuts for XPath errors, only the wrong_syntax
    def wrong_syntax(self, message=None, code='XPST0003'):
        if self.symbol == '::' and self.parser.token.symbol == '(name)':
            return self.missing_axis(message or "Axis '%s::' not found" % self.parser.token.value)
        elif self.symbol == '(' and getattr(self.parser.token, 'symbol', None) == '(name)':
            if self.parser.token.label == 'literal':
                msg = 'name {!r} cannot have arguments'
                return self.error('XPST0017', msg.format(self.parser.token.value))
        elif self.symbol == 'is' and self.label == 'operator' and \
                getattr(self.parser.next_token, 'symbol', None) == '(':
            msg = '{} cannot have arguments'
            return self.error('XPST0017', msg.format(self))
        elif self.symbol in {'as', 'of'}:
            return self.error('XPDY0002')  # Dynamic context required

        if message:
            return self.error(code, message)
        else:
            error = super(XPathToken, self).wrong_syntax(message)
            return self.error(code, str(error))

    def wrong_value(self, message=None):
        return self.error('FOCA0002', message)

    def wrong_type(self, message=None):
        return self.error('FORG0006', message)

    def missing_schema(self, message=None):
        return self.error('XPST0001', message)

    def missing_context(self, message=None):
        return self.error('XPDY0002', message)

    def wrong_context_type(self, message=None):
        return self.error('XPTY0004', message)

    def missing_sequence(self, message=None):
        return self.error('XPST0005', message)

    def missing_name(self, message=None):
        return self.error('XPST0008', message)

    def missing_axis(self, message=None):
        return self.error('XPST0010', message)

    def wrong_nargs(self, message=None):
        return self.error('XPST0017', message)

    def wrong_step_result(self, message=None):
        return self.error('XPTY0018', message)

    def wrong_intermediate_step_result(self, message=None):
        return self.error('XPTY0019', message)

    def wrong_axis_argument(self, message=None):
        return self.error('XPTY0020', message)

    def wrong_sequence_type(self, message=None):
        return self.error('XPDY0050', message)

    def unknown_atomic_type(self, message=None):
        return self.error('XPST0051', message)

    def wrong_target_type(self, message=None):
        return self.error('XPST0080', message)

    def unknown_namespace(self, message=None):
        return self.error('XPST0081', message)
