import json, decimal

from django.core.serializers import serialize
from django.conf import settings
from django.utils.module_loading import import_string
from django.template import RequestContext, Template, loader
from django.contrib.contenttypes.models import ContentType

import models

try:
    from django.utils import timezone
except ImportError:
    from datetime import datetime as timezone


CART_ID = 'CART-ID'

class DecimalEncoder(json.JSONEncoder):
    def _iterencode(self, o, markers=None):
        if isinstance(o, decimal.Decimal):
            # wanted a simple yield str(o) in the next line,
            # but that would mean a yield on the line with super(...),
            # which wouldn't work, so...
            return (str(o) for o in [o])
        return super(DecimalEncoder, self)._iterencode(o, markers)

class ItemAlreadyExists(Exception):
    pass


class ItemDoesNotExist(Exception):
    pass


class CartDoesNotExist(Exception):
    pass


class UserDoesNotExist(Exception):
    pass


class CartProxy:
    def __init__(self, request, cart=None):
        # we pass none for a request when we just want a proxy
        if request is not None:
            user = request.user
        try:
            #First search by user
            if not user.is_anonymous():
                cart = models.Cart.objects.get(user=user, checked_out=False)
            #If not, search by request id
            else:
                user = None
                cart_id = request.session.get(CART_ID)
                cart = models.Cart.objects.get(id=cart_id, checked_out=False)
        except:
            if cart is None:
                cart = self.new(request, user=user)
            else:
                cart = models.Cart.objects.get(id=cart.id)

        self.request = request
        self.cart = cart

    def __iter__(self):
        for item in self.cart.item_set.all():
            yield item

    @classmethod
    def get_cart(self, request):
        cart_id = request.session.get(CART_ID)
        if cart_id:
            cart = models.Cart.objects.get(id=cart_id, checked_out=False)
        else:
            cart = None
        return cart

    def new(self, request, user=None):
        cart = models.Cart(creation_date=timezone.now(), user=user)
        cart.save()
        request.session[CART_ID] = cart.id
        return cart

    def add(self, product, unit_price, quantity=1):
        try:
            ctype = ContentType.objects.get_for_model(type(product), for_concrete_model=False)
            item = models.Item.objects.get(cart=self.cart, product=product, content_type=ctype)
        except models.Item.DoesNotExist:
            item = models.Item()
            item.cart = self.cart
            item.product = product
            item.unit_price = unit_price
            item.quantity = quantity
            item.save()
        else:
            item.quantity += int(quantity)
            item.save()
        return item

    def remove_item(self, item_id):
        try:
            self.cart.item_set.filter(id=item_id).delete()
        except models.Item.DoesNotExist:
            raise ItemDoesNotExist

    def update_item(self, item_pk, new_quantity):
        try:
            item = models.Item.objects.get(pk=item_pk)
            item.quantity = new_quantity
            item.save()
        except models.Item.DoesNotExist:
            raise ItemDoesNotExist

    def update(self, product, quantity, unit_price=None):
        try:
            item = models.Item.objects.get(cart=self.cart, product=product)
            item.quantity = quantity
            item.save()
        except models.Item.DoesNotExist:
            raise ItemDoesNotExist

    def delete_old_cart(self, user):
        try:
            cart = models.Cart.objects.get(user=user)
            cart.delete()
        except models.Cart.DoesNotExist:
            pass

    def is_empty(self):
        return self.cart.is_empty()

    def replace(self, cart_id, new_user):
        try:
            self.delete_old_cart(new_user)
            cart = models.Cart.objects.get(pk=cart_id)
            cart.user = new_user
            cart.save()
            return cart
        except models.Cart.DoesNotExist:
            raise CartDoesNotExist

        return None

    def clear(self):
        for item in self.cart.item_set.all():
            item.delete()

    def get_item(self, item):
        try:
            obj = models.Item.objects.get(pk=item)
        except models.Item.DoesNotExist:
            raise ItemDoesNotExist

        return obj

    def total(self):
        """
        The total price of all items in the cart
        """
        return sum([item.total_price for item in self.cart.item_set.all()])

    def shipping_total(self):
        ship_f = import_string(settings.CART_SHIPPING_FUNCTION)
        return ship_f(self.cart.item_set.all(),
                import_string(settings.CART_SHIPPING_WEIGHT_COST))

    def total_inclusive(self):
        return self.total() + self.shipping_total()

    def count(self):
        """
        The number of items in the cart, sum of quantities
        """
        return sum([item.quantity for item in self.cart.item_set.all()])

    def unique_count(self):
        """
        The number of items in the cart, sum of quantities
        """
        return len(list(self.cart.item_set.all()))

    def render_html(self, template="templates/cart_menu.html", context=None):
        """
        Returns a dict {'html': <html menu for cart>}
        """
        t = loader.get_template(template)
        if not context:
            c = RequestContext(self.request)
            html_rendered = t.render(c)
        else:
            c = RequestContext(self.request, context)
            html_rendered = t.render(c)
        return {'html':  html_rendered}

    def item_to_json(self, item, html=False, template="templates/cart_menu.html"):
        """
        Returns serialized json of `item`. If `html` is `True`, `template` will
        be rendered and appended to the list as a dictionary {'html':
        `rendered_html`}
        """
        item_dict = item.__dict__
        if html:
            item_dict['html'] = self.render_html_menu()['html']
        return json.dumps(item_dict, cls=DecimalEncoder) 

    def get_last_cart(self, user):
        try:
            cart = models.Cart.objects.get(user=user, checked_out=False)
        except models.Cart.DoesNotExist:
            self.cart.user = user
            self.cart.save()
            cart = self.cart
        return cart

    def checkout(self):
        cart = self.cart
        try:
            cart.checked_out = True
            cart.save()
        except models.Cart.DoesNotExist:
            pass

        return cart
