import { func, object } from "@dagger.io/dagger";

@object()
export class Repro {
  @func()
  hello(): string {
    return "hello";
  }
}
