// RUN: %dafny_0 /verifyAllModules /allocated:1 "%s" > "%t"
// RUN: %diff "%s.expect" "%t"
include "../../dafny0/CompilationErrors.dfy"
