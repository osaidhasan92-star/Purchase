import { useEffect } from "react";

// More than one dialog can be open (for example, the Admin company profile).
let locks = 0;
let previous: { element: HTMLElement; overflow: string; priority: string }[] =
  [];

export function useModalScrollLock(open = true) {
  useEffect(() => {
    if (!open) return;
    if (locks++ === 0) {
      previous = [document.documentElement, document.body].map((element) => ({
        element,
        overflow: element.style.getPropertyValue("overflow"),
        priority: element.style.getPropertyPriority("overflow"),
      }));
      for (const { element } of previous)
        element.style.setProperty("overflow", "hidden");
    }
    return () => {
      if (--locks === 0) {
        for (const { element, overflow, priority } of previous) {
          if (overflow)
            element.style.setProperty("overflow", overflow, priority);
          else element.style.removeProperty("overflow");
        }
        previous = [];
      }
    };
  }, [open]);
}
