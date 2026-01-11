import inspect
import typing

from django.core.management.base import BaseCommand, CommandError
from django.db import models

from core import tasks


class Command(BaseCommand):
    help = "Run any task from core/tasks.py"

    def add_arguments(self, parser):
        parser.add_argument(
            "task_name", type=str, help="Name of the task function in core/tasks.py"
        )
        parser.add_argument(
            "task_args",
            nargs="*",
            help="Arguments for the task. Format: 'value' for positional or 'key=value' for keyword arguments.",
        )

    def handle(self, *args, **options):
        task_name = options["task_name"]
        task_args = options["task_args"]

        if not hasattr(tasks, task_name):
            available_tasks = [
                t
                for t in dir(tasks)
                if inspect.isfunction(getattr(tasks, t)) and not t.startswith("_")
            ]
            raise CommandError(
                f"Task '{task_name}' not found. Available tasks: {', '.join(available_tasks)}"
            )

        task_func = getattr(tasks, task_name)
        sig = inspect.signature(task_func)
        params = list(sig.parameters.values())

        final_args = []
        final_kwargs = {}

        # Parse task_args into a list of (key, value) where key is None for positional
        parsed_inputs = []
        for arg in task_args:
            if "=" in arg:
                key, value = arg.split("=", 1)
                parsed_inputs.append((key, value))
            else:
                parsed_inputs.append((None, arg))

        # Map inputs to signature
        pos_idx = 0
        for key, value in parsed_inputs:
            if key:
                if key not in sig.parameters:
                    raise CommandError(f"Task '{task_name}' has no parameter '{key}'")
                param = sig.parameters[key]
                final_kwargs[key] = self._resolve_argument(value, param)
            else:
                if pos_idx >= len(params):
                    raise CommandError(f"Too many positional arguments for task '{task_name}'")
                param = params[pos_idx]
                if param.kind == inspect.Parameter.KEYWORD_ONLY:
                    raise CommandError(
                        f"Parameter '{param.name}' is keyword-only. Use {param.name}={value}"
                    )
                final_args.append(self._resolve_argument(value, param))
                pos_idx += 1

        self.stdout.write(f"Executing {task_name}(args={final_args}, kwargs={final_kwargs})...")

        try:
            result = task_func(*final_args, **final_kwargs)
            self.stdout.write(self.style.SUCCESS("Task completed successfully."))
            self.stdout.write(f"Result: {result}")
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Task failed: {e}"))
            raise CommandError(f"Execution Error: {e!s}") from e

    def _resolve_argument(self, value: str, param: inspect.Parameter):
        anno = param.annotation
        if anno is inspect.Parameter.empty:
            return self._parse_basic_value(value)

        # Get possible types from Union/Optional
        target_types = []
        origin = typing.get_origin(anno)
        if origin is typing.Union or (
            hasattr(typing, "UnionType") and isinstance(anno, typing.UnionType)
        ):
            target_types = typing.get_args(anno)
        else:
            target_types = [anno]

        # Try to resolve based on type hints
        for t in target_types:
            if t is type(None):
                if value.lower() == "none":
                    return None
                continue

            # Django Model resolution
            if inspect.isclass(t) and issubclass(t, models.Model):
                try:
                    # Try to fetch by ID
                    return t.objects.get(id=value)
                except (t.DoesNotExist, ValueError):
                    # Continue to try other types in Union, or fallback
                    continue

            if t is bool:
                if value.lower() in ("true", "1", "yes", "t"):
                    return True
                if value.lower() in ("false", "0", "no", "f"):
                    return False

            if t is int:
                try:
                    return int(value)
                except ValueError:
                    continue

            if t is float:
                try:
                    return float(value)
                except ValueError:
                    continue

            if t is str:
                return value

        # Fallback to basic parsing if no type matched
        return self._parse_basic_value(value)

    def _parse_basic_value(self, value: str):
        if value.lower() == "none":
            return None
        if value.lower() == "true":
            return True
        if value.lower() == "false":
            return False
        try:
            if "." in value:
                return float(value)
            return int(value)
        except ValueError:
            return value
