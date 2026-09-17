from django_redis.cache import RedisCache as BaseRedisCache


class RedisCache(BaseRedisCache):

    # Usages to cache.keys() across the codebase assume that .keys will _always_ return a list
    def keys(self, *args, **kwargs):
        return super().keys(*args, *kwargs) or []
