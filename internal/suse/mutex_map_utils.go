package suse

import (
	"sync"
)

// smol stdlib here to deal with goroutine safe maps
type MutexMap[K comparable, V any] struct {
	l *sync.RWMutex
	m map[K]V
}

func NewMutexMap[K comparable, V any]() MutexMap[K, V] {
	return MutexMap[K, V]{
		m: make(map[K]V, 0),
		l: &sync.RWMutex{},
	}
}
func GetFromMapping[K comparable, V any](target MutexMap[K, V], key K) (V, bool) {
	target.l.RLock()
	defer target.l.RUnlock()
	v, ok := target.m[key]
	return v, ok
}

func DeleteFromMapping[K comparable, V any](target MutexMap[K, V], key K) {
	target.l.Lock()
	defer target.l.Unlock()
	delete(target.m, key)
}

func SetKeyInMapping[K comparable, V any](target MutexMap[K, V], key K, value V) {
	target.l.Lock()
	defer target.l.Unlock()
	target.m[key] = value
}

func IterateMap[K comparable, V any](target MutexMap[K, V], yield func(key K, value V) bool) {
	target.l.RLock()
	defer target.l.RUnlock()
	for key, value := range target.m {
		if !yield(key, value) {
			break
		}
	}
}

func MapSize[K comparable, V any](target MutexMap[K, V]) int {
	target.l.RLock()
	defer target.l.RUnlock()
	return len(target.m)
}

type GenericMarkMapping[K comparable] = map[K]struct{}

func NewGenericMarkMapping[K comparable]() GenericMarkMapping[K] {
	return make(GenericMarkMapping[K])
}

func SweepMap[K comparable, V any](target MutexMap[K, V], marks GenericMarkMapping[K]) {
	var deletes []K

	IterateMap(target, func(key K, _ V) bool {
		if _, ok := marks[key]; !ok {
			deletes = append(deletes, key)
		}
		return true
	})

	for _, key := range deletes {
		DeleteFromMapping(target, key)
	}
}
