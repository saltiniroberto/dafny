// RUN: %dafny_0 /compile:0 "%s" > "%t"
// RUN: %diff "%s.expect" "%t"

predicate P() {
  forall m:mode :: m == m
}
