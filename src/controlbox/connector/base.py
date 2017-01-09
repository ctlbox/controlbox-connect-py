import logging
from abc import abstractmethod

from controlbox.conduit.base import Conduit, StreamErrorReportingConduit
from controlbox.protocol.async import UnknownProtocolError
from controlbox.support.events import EventSource
from controlbox.support.mixins import CommonEqualityMixin

logger = logging.getLogger(__name__)


class ConnectorError(Exception):
    """ Indicates an error condition with a connection. """


class ConnectionNotConnectedError(ConnectorError):
    """ Indicates a connection is in the disconnected state when a connection is required. """


class ConnectionNotAvailableError(ConnectorError):
    """ Indicates the connection is not available. """


class ConnectorEvent(CommonEqualityMixin):
    """ base class for connector events. """
    def __init__(self, connector):
        self.connector = connector


class ConnectorConnectedEvent(ConnectorEvent):
    """ The connector was connected. """


class ConnectorDisconnectedEvent(ConnectorEvent):
    """ The connector was disconnected. """


class Connector():
    """ A connector describes an endpoint to which a conduit can be established. """

    def __init__(self):
        self.events = EventSource()

    @property
    @abstractmethod
    def endpoint(self):
        """ the endpoint that this connector reaches out to """
        raise NotImplementedError

    @property
    @abstractmethod
    def connected(self) -> bool:
        """
        Determines if this connector is connected to its underlying resource.
        :return: True if this connector is connected to it's underlying resource. False otherwise.
        :rtype: bool
        """
        raise NotImplementedError

    @property
    @abstractmethod
    def conduit(self) -> Conduit:
        """
        Retrieves the conduit for this connection.
        If the connection is not connected, raises NotConnectedError
        :return:
        :rtype:
        """
        raise NotImplementedError

    @property
    @abstractmethod
    def available(self) -> bool:
        """ Determines if the underlying resource for this connector is available.
        :return: True if the resource is available and can be connected to.
        If this resource is connected and available is true, then it means it is a multi-instance
        resource that can support multiple connections.
        :rtype: bool
        """
        raise NotImplementedError

    @abstractmethod
    def connect(self):
        """
        Connects this connector to the underlying resource and determines the protocol.
        If the connection is already connected,
        this method returns silently.
        Raises ConnectionError if the connection cannot be established.
        :return:
        :rtype:
        """
        raise NotImplementedError

    @abstractmethod
    def disconnect(self):
        raise NotImplementedError


class AbstractConnector(Connector):
    """ Manages the connection cycle to an endpoint.
        This class adds some robustness to the standard methods so that subclasses don't need to perform
        state checks when implementing template methods like _connect, _disconnect.
    """

    def __init__(self):
        super().__init__()
        self._conduit = None

    @property
    def available(self):
        return False if self.connected else self._try_available()

    @property
    def connected(self):
        return self._conduit is not None and self._connected()

    def connect(self):
        if self.connected:
            return

        if not self.available:
            raise ConnectionNotAvailableError

        try:
            self._conduit = self._connect()
        finally:
            if not self._conduit:
                self.disconnect()
            else:
                self.events.fire(ConnectorConnectedEvent(self))

    def disconnect(self):
        if self._conduit is None:
            return
        conduit = self._conduit
        self._conduit = None
        self._disconnect()
        conduit.close()
        self.events.fire(ConnectorDisconnectedEvent(self))

    @abstractmethod
    def _connect(self) -> Conduit:
        """ Template method for subclasses to perform the connection.
            If connection is not possible, an exception should be thrown
        """
        raise NotImplementedError

    @abstractmethod
    def _try_available(self):
        """ Determine if this connection is available. This method is only called when
            the connection is disconnected.
        :return: True if the connection is available or False otherwise.
        :rtype: bool
        """
        raise NotImplementedError

    @abstractmethod
    def _disconnect(self):
        """ perform any actions needed on disconnection.
        The base class takes care of disposing the protocol and the conduit, which happens
        after this method has been called.
        """
        raise NotImplementedError

    def _connected(self):
        return self._conduit.open

    @property
    def conduit(self) -> Conduit:
        """
        Retrieves the conduit for this connection.
        raises ConnectionNotConnectedError if not connected
        """
        self.check_connected()
        return self._conduit

    def check_connected(self):
        if not self.connected:
            raise ConnectionNotConnectedError


class DelegateConnector(Connector):
    """
    Delegates methods to the delegate connector, unless they are overridden
    """
    def __init__(self, delegate):
        super().__init__()
        self.delegate = delegate

    @property
    def available(self) -> bool:
        return self.delegate.available

    @property
    def conduit(self) -> Conduit:
        return self.delegate.conduit

    @property
    def endpoint(self):
        return self.delegate.endpoint

    @property
    def connected(self) -> bool:
        return self.delegate.connected

    def connect(self):
        return self.delegate.connect()

    def disconnect(self):
        return self.delegate.disconnect()


class AbstractDelegateConnector(AbstractConnector):
    """
    Delegates methods to the delegate connector, unless they are overridden
    """
    def __init__(self, delegate):
        super().__init__()
        self.delegate = delegate
        delegate.events.add(self._delegate_events)

    def _delegate_events(self, event):
        """ closes this connector when the wrapped connector closes. """
        if isinstance(event, ConnectorDisconnectedEvent):
            self.disconnect()

    def _try_available(self):
        return self.delegate.available

    def _connect(self) -> Conduit:
        self.delegate.connect()
        wrapped = self._wrap_conduit(self.delegate.conduit)
        return wrapped

    def _wrap_conduit(self, conduit) -> Conduit:
        return conduit

    def _disconnect(self):
        self.delegate.disconnect()

    def _connected(self) -> bool:
        return self.delegate.connected

    @property
    def endpoint(self):
        return self.delegate.endpoint


# class ConnectorContextManager:
#     """
#     Opens the connector on entry, and closes it on exit.
#     """
#
#     def __init__(self, connector: Connector):
#         self.connector = connector
#
#     def __enter__(self):
#         try:
#             logger.debug("Detected device on %s" % self.connector.conduit.target)
#             self.connector.connect()
#             logger.debug("Connected device on %s using protocol %s" %
#                          (self.connector.endpoint, self.connector.protocol))
#         except ConnectorError as e:
#             s = str(e)
#             logger.error("Unable to connect to device on %s - %s" %
#                          (self.connector.endpoint, s))
#             raise e
#
#     def __exit__(self):
#         logger.debug("Disconnected device on %s" % self.connector.endpoint)
#         self.connector.disconnect()


class CloseOnErrorConnector(AbstractDelegateConnector):
    """
    Detects any exceptions thrown reading/writing to the stream and closes the connector.
    """
    def __init__(self, delegate):
        super().__init__(delegate)

    def _wrap_conduit(self, conduit):
        return StreamErrorReportingConduit(conduit, self.on_stream_exception)

    def on_stream_exception(self):
        self.disconnect()


class ProtocolConnector(AbstractDelegateConnector):
    """A connection that must satisfy protocol requirements before being considered open.

    The protocol is available as the `protocol` property. The ProtocolConnector is set
    on the protocol as the connector attribute.
    """
    def __init__(self, delegate: Connector, protocol_sniffer):
        """
        :param delegate: The connector to delegate to (this provides the conduit over which the protocol is carried)
        :param protocol_sniffer: a function, that on given the conduit, determines the protocol to use.
        """
        super().__init__(delegate)
        self._sniffer = protocol_sniffer
        self._protocol = None

    def _connect(self)->Conduit:
        result: Conduit = super()._connect()
        try:
            self._protocol = self._sniffer(result)
            if self._protocol is None:
                raise UnknownProtocolError("Protocol sniffer did not return a protocol.")
            else:
                self._protocol.connector = self
        except UnknownProtocolError as e:
            raise ConnectorError() from e
        finally:  # cleanup connection on protocol error
            if self._protocol is None:
                result.close()
                self._disconnect()
        return result

    def _connected(self):
        return self._protocol is not None

# todo - invoking the chained connector should happen in the base class for consistency
    def _disconnect(self):
        protocol = self._protocol
        self._protocol = None
        if protocol is not None:
            if hasattr(protocol, 'shutdown'):
                protocol.shutdown()
        self.delegate.disconnect()

    @property
    def protocol(self):
        return self._protocol
