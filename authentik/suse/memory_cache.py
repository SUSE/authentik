import re

from django.core.cache.backends.locmem import LocMemCache


class MemoryCache(LocMemCache):
    def reverse_key_func(self, generated_key):
        # the default cache key function is prefix:version:key
        # this one returns the last piece
        return generated_key.split(":", 2)[-1]

    def keys(self, keys_pattern, version=None):
        keys_pattern = self.make_key(keys_pattern.replace("*", ".*"), version=version)

        with self._lock:
            return [
                self.reverse_key_func(key)
                for key in self._cache
                if not self._has_expired(key) and re.match(keys_pattern, key)
            ]
