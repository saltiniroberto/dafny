include "../Interp.dfy"
include "../CompilerCommon.dfy"
include "../Printer.dfy"
include "../Library.dfy"
include "../CSharpInterop.dfy"
include "../CSharpDafnyASTModel.dfy"
include "../CSharpDafnyInterop.dfy"
include "../../AutoExtern/CSharpModel.dfy"

import DafnyCompilerCommon.AST
import DafnyCompilerCommon.Translator
import opened Lib.Datatypes
import opened CSharpDafnyInterop

module {:extern "REPLInterop"} {:compile false} REPLInterop {
  import System
  import C = CSharpDafnyASTModel

  class {:compile false} {:extern} Utils {
    constructor {:extern} () requires false

    static method {:extern} Initialize()

    static method {:extern} ReadLine()
      returns (e: System.String?)
  }

  trait {:compile false} {:extern} ParseResult {
    lemma Sealed()
      ensures || this is IncompleteParse
              || this is ParseError
              || this is SuccessfulParse
  }
  class {:compile false} {:extern} IncompleteParse extends ParseResult {
    lemma Sealed() {}
    constructor {:extern} () requires false
  }
  class {:compile false} {:extern} ParseError extends ParseResult {
    lemma Sealed() {}
    constructor {:extern} () requires false
    var {:extern} Message: System.String;
  }
  class {:compile false} {:extern} SuccessfulParse extends ParseResult {
    method {:extern} Resolve() returns (r: ResolutionResult)
    lemma Sealed() {}
  }

  trait {:compile false} {:extern} ResolutionResult {
    lemma Sealed()
      ensures || this is ResolutionError
              || this is TypecheckedProgram
  }
  class {:compile false} {:extern} ResolutionError extends ResolutionResult {
    lemma Sealed() {}
    constructor {:extern} () requires false
    var {:extern} Message: System.String;
  }
  class {:compile false} {:extern} TypecheckedProgram extends ResolutionResult {
    lemma Sealed() {}
    constructor {:extern} () requires false
    var {:extern} NewInputs: System.Collections.Generic.List<UserInput>;
  }

  trait {:compile false} {:extern} UserInput {
    lemma Sealed()
      ensures || this is ExprInput
    var {:extern} FullName: System.String;
    var {:extern} ShortName: System.String;
  }
  class {:compile false} {:extern} ExprInput extends UserInput {
    lemma Sealed() {}
    constructor {:extern} () requires false
    var {:extern} Body: C.Expression;
  }

  class {:compile false} {:extern} REPLState {
    constructor {:extern} ()
    method {:extern} TryParse(input: System.String) returns (p: ParseResult)
  }
}

datatype REPLError =
  | EOF()
  | ParseError(pmsg: string)
  | ResolutionError(rmsg: string)
  | TranslationError(te: Translator.TranslationError)
  | InterpError(ie: Interp.InterpError)
  | Unsupported(e: AST.Expr)
{
  function method ToString() : string {
    match this
      case EOF() =>
        "EOF"
      case ParseError(msg) =>
        "Parse error:\n" + msg
      case ResolutionError(msg) =>
        "Resolution error:\n" + msg
      case TranslationError(te) =>
        "Translation error: " + te.ToString()
      case InterpError(ie) =>
        "Execution error: " + ie.ToString()
      case Unsupported(ex) =>
        "Unsupported expression" // FIXME change checker to return the unsupported subexpression
  }
}

type REPLResult<+A> = Result<A, REPLError>

datatype Named<+A> = Named(fullName: string, shortName: string, body: A)

class REPL {
  var state: REPLInterop.REPLState;
  var globals: Interp.Context;
  var counter: int;

  constructor() {
    state := new REPLInterop.REPLState();
    globals := map[];
    counter := 0;
  }

  static method ReadLine(prompt: string)
    returns (o: Option<string>)
    ensures o.Some? ==> o.value != ""
    decreases *
  {
    while true
      decreases *
    {
      print prompt;
      var line := REPLInterop.Utils.ReadLine();
      if line == null {
        return None;
      } else {
        var line := TypeConv.AsString(line);
        if line == "" {
          continue;
        } else {
          return Some(line);
        }
      }
    }
  }

  method Read() returns (r: REPLResult<REPLInterop.SuccessfulParse>)
    modifies this`counter // DISCUSS: Order?
    decreases *
  {
    var prompt := "dfy[" + Lib.Str.of_int(counter) + "] ";
    var input: string := "";
    counter := counter + 1;
    while true
      invariant |prompt| > 0
      decreases *
    {
      var line := ReadLine(prompt);
      match line {
        case Some(l) =>
          input := input + l + "\n";
        case None =>
          return Failure(EOF());
      }

      var parsed: REPLInterop.ParseResult :=
        state.TryParse(StringUtils.ToCString(input));
      if parsed is REPLInterop.IncompleteParse {
        prompt := if prompt[0] == '.' then prompt else seq(|prompt| - 1, _ => '.') + " ";
        continue;
      } else if parsed is REPLInterop.ParseError {
        var p := parsed as REPLInterop.ParseError; // BUG(1731)
        return Failure(ParseError(TypeConv.AsString(p.Message)));
      } else {
        parsed.Sealed();
        return Success(parsed as REPLInterop.SuccessfulParse);
      }
    }
  }

  function method TranslateInput(input: REPLInterop.UserInput)
    : REPLResult<Named<Interp.Expr>>
    reads *
  {
    var fullName := TypeConv.AsString(input.FullName);
    var shortName := TypeConv.AsString(input.ShortName);
    var body :-
      if input is REPLInterop.ExprInput then
        var ei := input as REPLInterop.ExprInput;
        DafnyCompilerCommon.Translator.TranslateExpression(ei.Body)
          .MapFailure(e => TranslationError(e))
      else
        (input.Sealed();
         Lib.ControlFlow.Unreachable());
    :- Need(Interp.SupportsInterp(body), Unsupported(body));
    Success(Named(fullName, shortName, body))
  }

  method ReadResolve() returns (r: REPLResult<seq<Named<Interp.Expr>>>)
    modifies this`counter
    decreases *
  {
    var inputs :- Read();

    var tcRes: REPLInterop.ResolutionResult := inputs.Resolve();
    if tcRes is REPLInterop.ResolutionError {
      var err := tcRes as REPLInterop.ResolutionError;
      return Failure(ResolutionError(TypeConv.AsString(err.Message)));
    }

    tcRes.Sealed();
    var newInputs :=
      var tp := tcRes as REPLInterop.TypecheckedProgram;
      CSharpInterop.ListUtils.ToSeq(tp.NewInputs);
    return Lib.Seq.MapResult(newInputs, TranslateInput);
  }

  static method Eval(e: Interp.Expr, globals: Interp.Context) returns (r: REPLResult<Interp.Value>)
    decreases *
  {
    var fuel: nat := 4;
    while true
      decreases *
    {
      var env := Interp.Environment(fuel := fuel, globals := globals);
      match Interp.InterpExpr(e, env)
        case Success(Return(val, _)) =>
          return Success(val);
        case Failure(OutOfFuel(_)) =>
          print "Trying again with fuel := ", fuel;
          fuel := fuel * 2;
        case Failure(err) =>
          return Failure(InterpError(err));
    }
  }

  method ReadEval()
    returns (r: REPLResult<seq<Named<Interp.Value>>>)
    modifies this`counter, this`globals
    decreases *
  {
    var rds :- ReadResolve();

    var idx := 0;
    var outputs := [];
    for idx := 0 to |rds| {
      var Named(fullName, shortName, body) := rds[idx];
      var val :- Eval(body, globals);
      globals := globals[fullName := val];
      outputs := outputs + [Named(fullName, shortName, val)];
    }

    return Success(outputs);
  }
}

method Main()
  decreases *
{
  REPLInterop.Utils.Initialize();
  var repl := new REPL();
  while true
    decreases * {
    var r := repl.ReadEval();
    match r {
      case Failure(EOF()) =>
        return;
      case Failure(err) =>
        print err.ToString();
      case Success(results) =>
        for idx := 0 to |results| {
          var Named(_, shortName, val) := results[idx];
          print shortName, " := ", Interp.Printer.ToString(val);
        }
    }
    print "\n";
  }
}