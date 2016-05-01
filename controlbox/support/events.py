

class EventSource(object):

    def __init__(self):
        self._handlers = []

    def __iadd__(self, handler):
        return self.add(handler)

    def __isub__(self, handler):
        return self.remove(handler)

    def add(self, handler):
        self._handlers.append(handler)
        return self

    def remove(self, handler):
        if handler in self._handlers:
            self._handlers.remove(handler)
        return self

    def fire(self, *args, **keywargs):
        for handler in self._handlers:
            handler(*args, **keywargs)

    def fire_all(self, events):
        for e in events:
            self.fire(e)
