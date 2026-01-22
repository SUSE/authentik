# User-defined settings
from authentik.lib.config import CONFIG

# S3 Configuration
AWS_S3_OBJECT_PARAMETERS = CONFIG.get_dict_from_b64_json("suse.aws_s3_object_parameters", {})
CONFIG.log("info", "Loaded AWS_S3_OBJECT_PARAMETERS={}".format(AWS_S3_OBJECT_PARAMETERS))

CONFIG.log("info", "Loaded user_settings")
