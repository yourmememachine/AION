# Cycle 28 — failing-first evidence

Pre-change tree (1785 tests OK, skipped=28):

1. tests/test_cycle28_history_reconciliation.py was written
   before the implementation. On the pre-change tree the whole
   file fails at import — ModuleNotFoundError: No module named
   'trust.history_reconciliation' — because the top-level
   import of the not-yet-existing module fails. The detection
   the tests pin was absent, not merely failing. (This also
   means no individual test in the file could run pre-change;
   an earlier draft of this record wrongly implied test_17 had
   been run pre-change — corrected in the cycle-28 fix round
   at rev-r3/rev-r6's finding.)
2. The behavioural hole the import failure stands for is
   demonstrated post-change by the wired/unwired pair
   test_16/test_17: on the restored-store scenario (pin-store
   file restored to its genesis generation while the
   consumption journal holds a seq-3 ceremony the store
   lacks), the UNWIRED adopter — byte-for-byte the
   pre-cycle-28 adopter — raises no history-completeness
   signal of any kind (it stops as supersession-pending
   against the advanced head), while the WIRED adopter
   refuses with pin_store_history_incomplete naming the
   missing authorisation. The silence in the unwired run is
   the pre-change behaviour, reproduced in-tree.
