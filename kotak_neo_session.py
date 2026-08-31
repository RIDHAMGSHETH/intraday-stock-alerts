import os
import sys
import json
import pyotp

SDK_DIR = os.path.dirname(os.path.abspath(__file__))
if SDK_DIR not in sys.path:
    sys.path.append(SDK_DIR)

from neo_api_client import NeoAPI

# Exact NSE CM Instrument Tokens for your 4 winning stocks
KOTAK_TOKENS = {
    "MCX": {"token": "31181", "symbol": "MCX-EQ"},
    "DIXON": {"token": "21690", "symbol": "DIXON-EQ"},
    "BSE": {"token": "19585", "symbol": "BSE-EQ"},
    "CDSL": {"token": "21174", "symbol": "CDSL-EQ"}
}

class KotakNeoManager:
    def __init__(self):
        self.consumer_key = os.getenv("KOTAK_CONSUMER_KEY", "b82e6d38-df1e-4c35-b7a5-3ac7bfcb2894")
        self.mobile_number = os.getenv("KOTAK_MOBILE_NUMBER", "+919429963926")
        self.ucc = os.getenv("KOTAK_UCC", "XX7H9")
        self.mpin = os.getenv("KOTAK_MPIN", "811781")
        self.totp_secret = os.getenv("KOTAK_TOTP_SECRET", "K67KTJPNY632FJ7LUCNX6CPITA")
        self.client = None
        self.is_authenticated = False

    def authenticate(self) -> bool:
        if not self.consumer_key or not self.totp_secret:
            return False
        try:
            self.client = NeoAPI(environment="prod", consumer_key=self.consumer_key)
            totp_code = pyotp.TOTP(self.totp_secret).now()
            res_totp = self.client.totp_login(mobile_number=self.mobile_number, ucc=self.ucc, totp=totp_code)
            
            if isinstance(res_totp, dict) and res_totp.get("data", {}).get("token"):
                res_mpin = self.client.totp_validate(mpin=self.mpin)
                if isinstance(res_mpin, dict) and res_mpin.get("data", {}).get("token"):
                    self.is_authenticated = True
                    name = res_mpin.get("data", {}).get("greetingName", "Trader")
                    print(f"[Kotak Neo API] Authenticated successfully for UCC {self.ucc} ({name})")
                    return True
        except Exception as e:
            print(f"[Kotak Neo API] Login error: {e}")
        return False

    def get_live_quotes(self) -> dict:
        """Fetches direct institutional exchange LTP ticks for MCX, DIXON, BSE, CDSL."""
        if not self.is_authenticated:
            if not self.authenticate():
                return {}

        tokens_list = [
            {"instrument_token": info["token"], "exchange_segment": "nse_cm"}
            for info in KOTAK_TOKENS.values()
        ]
        
        try:
            resp = self.client.quotes(instrument_tokens=tokens_list, quote_type="ltp")
            prices = {}
            if isinstance(resp, list):
                # Reverse map token to stock name
                token_to_name = {info["token"]: name for name, info in KOTAK_TOKENS.items()}
                for item in resp:
                    t = str(item.get("exchange_token", ""))
                    if t in token_to_name:
                        name = token_to_name[t]
                        prices[name] = float(item.get("ltp", 0.0))
            return prices
        except Exception as e:
            print(f"[Kotak Neo API] Failed to fetch quotes: {e}")
            return {}

if __name__ == "__main__":
    mgr = KotakNeoManager()
    if mgr.authenticate():
        quotes = mgr.get_live_quotes()
        print("[Kotak Neo Live Exchange Ticks]:", quotes)
