from matplotlib.backends.backend_qt5agg import NavigationToolbar2QT


class NavigationToolbar(NavigationToolbar2QT):

    def __init__(self, canvas, parent, coordinates=True,
                 button_blacklist=None):
        # This adds the option to blacklist some of the buttons for the
        # toolbar. Options are currently: Home, Back, Forward, Pan, Zoom,
        # Subplots, Save.
        # Blacklisting the None object removes separators.
        if button_blacklist is None:
            button_blacklist = []
        elif not isinstance(button_blacklist, (list, tuple)):
            button_blacklist = [button_blacklist]

        old_toolitems = NavigationToolbar2QT.toolitems
        NavigationToolbar2QT.toolitems = [
            x for x in NavigationToolbar2QT.toolitems
            if x[0] not in button_blacklist
        ]

        super().__init__(canvas, parent, coordinates)

        # Restore the global navigation tool items for other parts of
        # the program to use them.
        NavigationToolbar2QT.toolitems = old_toolitems
