"""This module returns the CA certificate bundle included with the agent.

"""

import os
# TODO 返回CA证书地址

def where():
    return os.path.join(os.path.dirname(__file__), 'cacert.pem')
