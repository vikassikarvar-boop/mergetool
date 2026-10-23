import os
import sys
import time
import json
import uuid
import urllib.parse
import hashlib
import requests
from Cryptodome.Cipher import AES, PKCS1_v1_5
from Cryptodome.PublicKey import RSA
from Cryptodome.Random import get_random_bytes

# Import existing core functions
import force_ipv4
from ig_login_perdevice import (
    make_device_fingerprint,
    get_device_profile_for_user,
    password_encrypt,
    totp_code,
    derive_cookies_from_token,
    extract_credentials,
    format_proxy_url,
    BASE,
    HERE,
    TEMPLATES,
    TEMPLATE_ANDROID_ID
)

# Load proxy list provided by user
raw_proxies = """
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-qCSq0pV1_lifetime-168h
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-xndsDl0Z_lifetime-168h
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-C2nLw6Y9_lifetime-168h
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-g3vHHoPP_lifetime-168h
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-Rb1VWG21_lifetime-168h
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-vklkhPcZ_lifetime-168h
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-8wCKt2rU_lifetime-168h
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-eq4JxpDY_lifetime-168h
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-mmmEPw95_lifetime-168h
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-B2u6zWOM_lifetime-168h
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-mxLW7lMG_lifetime-168h
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-y0YKUBxL_lifetime-168h
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-CYj28tJp_lifetime-168h
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-DFxKimR5_lifetime-168h
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-0cHBYwbH_lifetime-168h
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-YiXb8uhg_lifetime-168h
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-fmkQrbfl_lifetime-168h
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-wpHupo8v_lifetime-168h
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-734WPKAg_lifetime-168h
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-3Ms7Vuw6_lifetime-168h
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-6rQG3KWP_lifetime-168h
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-k1bVlNeo_lifetime-168h
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-exp8rln1_lifetime-168h
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-eO8jQMBA_lifetime-168h
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-BGqUggDL_lifetime-168h
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-XW4mFZF3_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-CwsSm565_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-CbABxQoo_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-XUA0IdIO_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-2uXv0qSQ_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-n4AFaWPu_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-eB5d2c16_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-JPFpT8Xq_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-vMQinjPd_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-4XutJL3L_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-jIyw3qss_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-t9JrDygz_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-r8s6orAS_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-4NkuKVdX_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-Vcfl3bxs_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-FW9UXHX7_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-QIPvJAB6_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-pOE9jk5T_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-PAO97jLH_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-nPtTsK6w_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-K9o7JLp9_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-ct7hWSdM_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-YAZ7miI0_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-Q66TJGeG_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-S1jo1vj4_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-3mXxFqY9_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-6b1Fypeg_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-NIM08zDV_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-7T1pVTOI_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-ZQ2T0mYD_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-Zv3mw3Dd_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-xLsrrpaP_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-YPD6bNVd_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-L5zk0ShN_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-zIHQQl1q_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-nia7v7EW_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-x6HeanOs_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-7mNx0lGc_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-j6XLCIMz_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-FSVExxYY_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-432j9Pkl_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-1O9T5JmG_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-FWZJw3JU_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-EqIQPyiC_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-O5JQKHWN_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-dH5NE64u_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-mgeOhwpj_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-rwOGS651_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-fadybe6H_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-kJI9ziVv_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-SEmcrarR_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-gxQemER7_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-y2P4AJ8Y_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-ZvUhQMTK_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-BZazF1Hl_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-dx9XTuNX_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-gMIUBHg1_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-c3quXhQ7_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-WvedNo57_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-0YV0vOKD_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-bfGIGSxv_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-N6sjLVMJ_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-v3vxEC05_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-pJkJsAWT_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-xixBgRSx_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-UGTExEoF_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-FMauUeU4_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-R7Mn0OSQ_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-0FHbG3q8_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-iR7PfwKp_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-Bg1mYOXw_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-VYWkJgyl_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-kZTXiXSp_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-n1aBdrFZ_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-CCN1TWuO_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-Qm3YTAty_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-F29J13xW_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-xq1Himwl_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-jnfa2r17_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-SjBI6N0N_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-7E2CYha8_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-vrgUv3cB_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-zbx8nfKA_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-US5kLIni_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-NGFaCCvK_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-jOrm0w5y_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-5e2UmWwE_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-gSHwhVfr_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-eD0etPYw_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-anvY1wk9_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-rXwixHSs_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-vwWv1aqY_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-kJCkoi5Z_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-zoFunpi8_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-ZoxtaOlX_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-tVU3dpDX_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-BopdeRhq_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-fykVAcCr_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-sC9tqkKD_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-O5o4m10K_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-r8WMKW5S_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-nGbHoKtG_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-M9vk2wa2_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-PM2PVeB6_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-yxpN9SX2_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-VVbHK4sr_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-uUX5Au5f_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-1LTDZOKe_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-Hn571Bbj_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-9kzX1VRr_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-ZTJlrrMH_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-4K2r0w7w_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-wULTrGJf_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-V99PQ0bx_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-Uylmo7xj_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-B4gZduWx_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-KoMI61XG_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-qqIzg739_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-lpOVIK3C_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-idHmklGI_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-Tf1zXHuB_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-MPNnQjIk_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-k37P1gdW_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-2zrpSvgl_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-VQDMdgRq_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-ib1CGX41_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-G3dP3nps_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-byZ3XGqd_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-FZ75Odb4_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-awaMNW4x_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-2dbT5dlN_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-QPwQvyrJ_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-KxW8ifkY_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-3ZkxROX3_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-dJbK8nEe_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-SUky6vOi_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-MFsfYhOs_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-LusDv2Ds_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-8FNGKxdd_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-QWpMNutn_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-1twYEhAC_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-cV5egb1m_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-RF5Ef0VH_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-bPkRo7wz_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-yeqvEkqK_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-PMbrSVVl_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-ber9SFoa_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-YKZmJFKW_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-3ZV2GfrE_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-53cEA2f0_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-t5ckWCyI_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-zbKbJE9x_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-B2BrA1qf_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-ph3FWpPd_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-m7odIkF8_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-0qmhHutZ_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-WouJ0yQU_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-YyunGLXT_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-4JyZ2wPZ_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-SBekeUCU_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-rz9MWTmy_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-G1fhQnLT_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-KBWMVLRQ_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-iUzUENoF_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-SMsDCM8t_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-sDCfFdvu_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-zVH3eV2O_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-gheuYMCX_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-qiChShKh_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-O3zw9KQI_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-7kS7zhFs_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-XeYhTanI_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-6DvKnkuw_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-ezq5Mhpp_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-67oxkkwU_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-AFbDql0R_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-Livfk4vn_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-JZKHElkm_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-VJFOpjhz_lifetime-59m
geo.iproyal.com:12321:HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-2QNAEuVV_lifetime-59m
"""

proxy_list = [format_proxy_url(p.strip()) for p in raw_proxies.strip().splitlines() if p.strip()]

def process_batch(max_accounts=10):
    # Load parttt 22.txt
    part22_path = r"D:\arena ai project\account format changer to server format\parttt 22.txt"
    accounts = []
    with open(part22_path, "r", encoding="utf-8") as f:
        for line in f:
            l = line.strip()
            if not l:
                continue
            parts = l.split(":")
            if len(parts) >= 3:
                accounts.append({
                    "username": parts[0].strip(),
                    "password": parts[1].strip(),
                    "totp": parts[2].strip(),
                    "raw": l
                })

    # Find which accounts already have cookies or are marked failed
    target_sub = os.path.join(HERE, "saved_cookies_part22")
    os.makedirs(target_sub, exist_ok=True)

    pending = []
    for acc in accounts:
        cookie_file = os.path.join(HERE, f"cookies_{acc['username']}.json")
        cookie_sub = os.path.join(target_sub, f"cookies_{acc['username']}.json")
        failed_file = os.path.join(HERE, f"cookies_{acc['username']}.failed.json")
        failed_sub = os.path.join(target_sub, f"cookies_{acc['username']}.failed.json")
        if os.path.exists(cookie_file) or os.path.exists(cookie_sub) or os.path.exists(failed_file) or os.path.exists(failed_sub):
            continue
        pending.append(acc)

    print("=" * 80)
    print(f"BATCH LOGIN RUNNER: {len(pending)} Pending Accounts | {len(proxy_list)} Proxies in Pool")
    print("=" * 80)

    to_run = pending[:max_accounts]
    print(f"Running next {len(to_run)} accounts in sequence...")

    results = []
    proxy_idx = 0

    for i, acc in enumerate(to_run, 1):
        uname = acc["username"]
        pwd = acc["password"]
        totp = acc["totp"]
        p_url = proxy_list[proxy_idx % len(proxy_list)]
        proxy_idx += 1

        print(f"\n[{i}/{len(to_run)}] PROCESSING @{uname} ...")
        cmd = (
            f'python "{os.path.join(HERE, "ig_login_perdevice.py")}" '
            f'--username "{uname}" '
            f'--password "{pwd}" '
            f'--totp-secret "{totp}" '
            f'--country UK '
            f'--proxy "{p_url}"'
        )

        t0 = time.time()
        ret = os.system(cmd)
        elapsed = time.time() - t0

        cookie_file = os.path.join(HERE, f"cookies_{uname}.json")
        success = (ret == 0) and os.path.exists(cookie_file)

        # If failed due to dirty proxy fake 'invalid_user', retry once with proven clean node
        if not success:
            print(f"[*] Retrying @{uname} with proven clean residential node (session-7usmXtiN)...")
            retry_cmd = (
                f'python "{os.path.join(HERE, "ig_login_perdevice.py")}" '
                f'--username "{uname}" '
                f'--password "{pwd}" '
                f'--totp-secret "{totp}" '
                f'--country UK '
                f'--proxy "http://HzCJlVVHqTVZkg19:rMdk9iqcygHj7gWF_country-gb_session-7usmXtiN_lifetime-59m@geo.iproyal.com:12321"'
            )
            ret2 = os.system(retry_cmd)
            success = (ret2 == 0) and os.path.exists(cookie_file)
            ret = ret2

        if success:
            import shutil
            dst = os.path.join(target_sub, f"cookies_{uname}.json")
            if os.path.exists(dst):
                os.remove(dst)
            shutil.move(cookie_file, dst)
            cookie_file = dst

        # Clean generic cookies.json in root if created
        gen_cookies = os.path.join(HERE, "cookies.json")
        if os.path.exists(gen_cookies):
            try:
                os.remove(gen_cookies)
            except Exception:
                pass

        status_str = "SUCCESS [VALID]" if success else "FAILED"
        print(f"[{i}/{len(to_run)}] @{uname} -> {status_str} (time: {elapsed:.1f}s)")

        results.append({
            "username": uname,
            "success": success,
            "exit_code": ret,
            "cookie_file": cookie_file if success else None
        })



        if not success:
            print(f"[!] WARNING: Account @{uname} failed. Checking next...")
            # If 3 consecutive fails happen, pause
            fails = [r for r in results[-3:] if not r["success"]]
            if len(fails) >= 3 and len(results) >= 3:
                print("\n[STOP] 3 consecutive failures encountered. Halting batch for inspection.")
                break

        time.sleep(2)

    print("\n" + "=" * 80)
    print("BATCH RUN SUMMARY:")
    print("=" * 80)
    succ_count = sum(1 for r in results if r["success"])
    print(f"Total Attempted : {len(results)}")
    print(f"Successful      : {succ_count}")
    print(f"Failed          : {len(results) - succ_count}")
    for r in results:
        sym = "[OK] " if r["success"] else "[FAIL]"
        print(f"  {sym} @{r['username']:<25} : {'SUCCESS' if r['success'] else 'FAILED'}")
    print("=" * 80)

if __name__ == "__main__":
    count = 10
    if len(sys.argv) > 1:
        try:
            count = int(sys.argv[1])
        except Exception:
            pass
    process_batch(max_accounts=count)

