import neo_api_client
from neo_api_client.exceptions import ApiException
from neo_api_client.settings import ORDER_SOURCE

class OrderAPI(object):
    def __init__(self, api_client):
        self.api_client = api_client
        self.rest_client = api_client.rest_client
        self.order_source = ORDER_SOURCE

    def order_placing(
            self,
            exchange_segment,
            product,
            price,
            order_type,
            quantity,
            validity,
            trading_symbol,
            transaction_type,
            amo=None,
            disclosed_quantity=None,
            market_protection=None,
            pf=None,
            trigger_price=None,
            tag=None,
            scrip_token=None,
            square_off_type=None,
            stop_loss_type=None,
            stop_loss_value=None,
            square_off_value=None,
            last_traded_price=None,
            trailing_stop_loss=None,
            trailing_sl_value=None,
    ):
        try:
            header_params = {
                "Authorization": f"Bearer {self.api_client.configuration.edit_token}",
                "neo-fin-key": self.api_client.configuration.get_neo_fin_key(),
                "Sid": self.api_client.configuration.edit_sid,
                "Auth": self.api_client.configuration.edit_token,
                "Content-Type": "application/x-www-form-urlencoded",
            }

            body_params = {
                "am": amo,
                "dq": disclosed_quantity,
                "es": exchange_segment,
                "mp": market_protection,
                "pc": product,
                "pf": pf,
                "pr": price,
                "pt": order_type,
                "qt": quantity,
                "rt": validity,
                "tp": trigger_price,
                "ts": trading_symbol,
                "tt": transaction_type,
                "ig": tag,
                "tk": scrip_token,
                "sot": square_off_type,
                "slt": stop_loss_type,
                "slv": stop_loss_value,
                "sov": square_off_value,
                "lat": last_traded_price,
                "tlt": trailing_stop_loss,
                "tsv": trailing_sl_value,
                "os": self.order_source,
            }

            query_params = {"sId": self.api_client.configuration.edit_sid}
            URL = self.api_client.configuration.get_url_details("place_order")
            orders_resp = self.rest_client.request(
                url=URL, method='POST',
                query_params=query_params,
                headers=header_params,
                body=body_params
            )

            try:
                return orders_resp.json()
            except Exception:
                return {"status_code": orders_resp.status_code, "text": orders_resp.text}
        except ApiException as ex:
            return {"error": ex}
