"""Target parsing (shared by the GUI and the CLI)."""
import ipaddress


def parse_targets(text: str) -> tuple:
    """'8.8.8.8, 1.1.1.0/24 2001:4860::8888' -> (valid, invalid)."""
    good, bad = [], []
    for tok in text.replace(",", " ").replace(";", " ").split():
        try:
            net = ipaddress.ip_network(tok, strict=False)
            good.append(tok if "/" not in tok else str(net))
        except ValueError:
            bad.append(tok)
    return good, bad
