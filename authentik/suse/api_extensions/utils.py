import dns
from django.core.cache import cache
from dns.resolver import Answer, CacheKey


class DjangoResolverCache(dns.resolver.Cache):
    CACHE_PREFIX = "SUSE/DNS"

    def _format_key(self, key: CacheKey):
        hostname = key[0].canonicalize().__str__()
        record_type = key[1].name.__str__()
        record_class = key[2].name.__str__()

        return f"{self.CACHE_PREFIX}/${hostname}/${record_type}/${record_class}"

    def get(self, key: CacheKey) -> Answer | None:
        return cache.get(self._format_key(key))

    def put(self, key: CacheKey, value: Answer) -> None:
        cache.set(self._format_key(key), value)

    def flush(self, key: CacheKey | None = None) -> None:
        if key is None:
            keys = cache.keys(f"{self.CACHE_PREFIX}/*")
            cache.delete_many(keys)
        else:
            cache.delete(self._format_key(key))


def first(result_set):
    for entry in result_set[:1]:
        return entry
    return None
