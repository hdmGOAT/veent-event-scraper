pkgs = ["nodriver", "undetected_chromedriver", "botasaurus", "seleniumbase", "patchright", "camoufox", "DrissionPage"]
for p in pkgs:
    try:
        m = __import__(p)
        ver = getattr(m, "__version__", "?")
        print(f"{p}: OK ({ver})")
    except ImportError:
        print(f"{p}: not installed")
