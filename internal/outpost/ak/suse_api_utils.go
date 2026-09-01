package ak

import (
	"iter"

	log "github.com/sirupsen/logrus"
)

// Automatically fetch all objects from an API endpoint using the pagination
// data received from the server.
func PaginatorIterator[Tobj any, Treq any, Tres PaginatorResponse[Tobj]](
	req PaginatorRequest[Treq, Tres],
	opts PaginatorOptions,
) iter.Seq2[Tobj, error] {

	if opts.Logger == nil {
		opts.Logger = log.NewEntry(log.StandardLogger())
	}

	return func(yield func(Tobj, error) bool) {
		var bfreq, cfreq interface{}
		fetchOffset := func(page int32) (Tres, error) {
			bfreq = req.Page(page)
			cfreq = bfreq.(PaginatorRequest[Treq, Tres]).PageSize(int32(opts.PageSize))

			opts.Logger.WithFields(log.Fields{
				"page":      page,
				"page-size": int32(opts.PageSize),
			}).Debug("Fetching page from instance")

			res, hres, err := cfreq.(PaginatorRequest[Treq, Tres]).Execute()
			if err != nil {
				opts.Logger.WithError(err).WithField("page", page).Warning("failed to fetch page")
				if hres != nil && hres.StatusCode >= 400 && hres.StatusCode < 500 {
					return res, err
				}
			}
			return res, err
		}

		var page int32 = 1
		for {
			apiObjects, err := fetchOffset(page)

			if err != nil {
				// original logic: If it fails on the first page, abort. but if it fails on a subsequent page, retry (?)
				var empty Tobj
				yield(empty, err)
				return
				// original logic: No idea why this was collecting errros, if it'd be either ignored or just be collecting errors to fail (?)
			}

			for _, item := range apiObjects.GetResults() {
				if !yield(item, nil) {
					return
				}
			}

			if apiObjects.GetPagination().Next > 0 {
				page += 1
			} else {
				break
			}
		}
	}
}
