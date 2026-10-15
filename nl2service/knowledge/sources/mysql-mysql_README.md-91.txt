	// Use sql.Tx transactions.
	// Define the transaction execution function fn. When the error returned by fn is nil, the transaction is automatically committed, otherwise the transaction is automatically rolled back.
	// Note: db operations in fn need to be executed using tx, otherwise they are not transactions.
	fn := func(tx *sql.Tx) (err error) {
		ql := "INSERT INTO qa_module_tags (game_id, tag_name) VALUES (?, ?), (?, ?)"
		if _, err = tx.Exec(ql, 1, "tag1", 2, "tag2"); err != nil {
			return
		}
		ql = "UPDATE qa_module_tags SET tag_name = ? WHERE game_id = ?"
		if _, err = tx.Exec(ql, "tag11", 1); err != nil {
			return
		}
		return
	}
	if err = proxy.Transaction(ctx, fn); err != nil {
		return
	}

